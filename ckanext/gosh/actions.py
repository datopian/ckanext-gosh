# encoding: utf-8

import logging
import json


import sqlalchemy
from paste.deploy.converters import asbool

import ckan.lib.dictization
import ckan.logic as logic
import ckan.logic.action
import ckan.logic.schema
import ckan.lib.dictization.model_dictize as model_dictize
import ckan.lib.navl.dictization_functions
import ckan.model as model
import ckan.model.misc as misc
import ckan.plugins as plugins
import ckan.lib.search as search
import ckan.lib.plugins as lib_plugins
import ckan.authz as authz

from ckan.common import _

log = logging.getLogger(__name__)


_validate = ckan.lib.navl.dictization_functions.validate
_check_access = logic.check_access
ValidationError = logic.ValidationError

_select = sqlalchemy.sql.select
_aliased = sqlalchemy.orm.aliased
_or_ = sqlalchemy.or_
_and_ = sqlalchemy.and_
_func = sqlalchemy.func
_desc = sqlalchemy.desc
_case = sqlalchemy.case
_text = sqlalchemy.text



@logic.side_effect_free
def package_autocomplete(context, data_dict):

    model = context['model']

    _check_access('package_autocomplete', context, data_dict)

    limit = data_dict.get('limit', 10)
    q = data_dict['q']

    like_q = u"%s%%" % q

    query = model.Session.query(model.Package)
    query = query.filter(model.Package.state == 'active')
    query = query.filter(model.Package.private == False)
    query = query.filter(_or_(model.Package.name.ilike(like_q),
                              model.Package.title.ilike(like_q)))
    
    query = query.limit(limit)

    q_lower = q.lower()
    pkg_list = []
    for package in query:
        if package.name.startswith(q_lower):
            match_field = 'name'
            match_displayed = package.name
        else:
            match_field = 'title'
            match_displayed = '%s (%s)' % (package.title, package.name)
        result_dict = {
            'name': package.name,
            'title': package.title,
            'match_field': match_field,
            'match_displayed': match_displayed}
        if not context.get("user", None) and package.extras.get("restricted", 0) == "1":
            continue
        pkg_list.append(result_dict)

    return pkg_list


@logic.side_effect_free
def package_search(context, data_dict):

    schema = (context.get('schema') or
              logic.schema.default_package_search_schema())
    data_dict, errors = _validate(data_dict, schema, context)
    # put the extras back into the data_dict so that the search can
    # report needless parameters
    data_dict.update(data_dict.get('__extras', {}))
    data_dict.pop('__extras', None)
    if errors:
        raise ValidationError(errors)

    model = context['model']
    session = context['session']
    user = context.get('user')

    _check_access('package_search', context, data_dict)

    # Move ext_ params to extras and remove them from the root of the search
    # params, so they don't cause and error
    data_dict['extras'] = data_dict.get('extras', {})
    for key in [key for key in data_dict.keys() if key.startswith('ext_')]:
        data_dict['extras'][key] = data_dict.pop(key)

    # check if some extension needs to modify the search params
    for item in plugins.PluginImplementations(plugins.IPackageController):
        data_dict = item.before_search(data_dict)

    # the extension may have decided that it is not necessary to perform
    # the query
    abort = data_dict.get('abort_search', False)

    if data_dict.get('sort') in (None, 'rank'):
        data_dict['sort'] = 'score desc, metadata_modified desc'

    results = []
    if not abort:
        if asbool(data_dict.get('use_default_schema')):
            data_source = 'data_dict'
        else:
            data_source = 'validated_data_dict'
        data_dict.pop('use_default_schema', None)
        # return a list of package ids
        data_dict['fl'] = 'id {0}'.format(data_source)

        # we should remove any mention of capacity from the fq and
        # instead set it to only retrieve public datasets
        fq = data_dict.get('fq', '')

        # Remove before these hit solr FIXME: whitelist instead
        include_private = asbool(data_dict.pop('include_private', False))
        include_drafts = asbool(data_dict.pop('include_drafts', False))

        capacity_fq = 'capacity:"public"'
        if include_private and authz.is_sysadmin(user):
            capacity_fq = None
        elif include_private and user:
            orgs = logic.get_action('organization_list_for_user')(
                {'user': user}, {'permission': 'read'})
            if orgs:
                capacity_fq = '({0} OR owner_org:({1}))'.format(
                    capacity_fq,
                    ' OR '.join(org['id'] for org in orgs))
            if include_drafts:
                capacity_fq = '({0} OR creator_user_id:({1}))'.format(
                    capacity_fq,
                    authz.get_user_id_for_username(user))

        if capacity_fq:
            fq = ' '.join(p for p in fq.split() if 'capacity:' not in p)
            data_dict['fq'] = fq + ' ' + capacity_fq

        fq = data_dict.get('fq', '')
        if include_drafts:
            user_id = authz.get_user_id_for_username(user, allow_none=True)
            if authz.is_sysadmin(user):
                data_dict['fq'] = fq + ' +state:(active OR draft)'
            elif user_id:
                # Query to return all active datasets, and all draft datasets
                # for this user.
                data_dict['fq'] = fq + \
                    ' ((creator_user_id:{0} AND +state:(draft OR active))' \
                    ' OR state:active)'.format(user_id)
        elif not authz.is_sysadmin(user):
            data_dict['fq'] = fq + ' +state:active'

        # Pop these ones as Solr does not need them
        extras = data_dict.pop('extras', None)

        query = search.query_for(model.Package)
        query.run(data_dict)

        # Add them back so extensions can use them on after_search
        data_dict['extras'] = extras

        for package in query.results:
            # get the package object
            package_dict = package.get(data_source)
            ## use data in search index if there
            if package_dict:
                # the package_dict still needs translating when being viewed
                package_dict = json.loads(package_dict)
                if context.get('for_view'):
                    for item in plugins.PluginImplementations(
                            plugins.IPackageController):
                        package_dict = item.before_view(package_dict)
                results.append(package_dict)
            else:
                log.error('No package_dict is coming from solr for package '
                          'id %s', package['id'])

        count = query.count
        facets = query.facets
    else:
        count = 0
        facets = {}
        results = []

    search_results = {
        'count': count,
        'facets': facets,
        'results': results,
        'sort': data_dict['sort']
    }

    # create a lookup table of group name to title for all the groups and
    # organizations in the current search's facets.
    group_names = []
    for field_name in ('groups', 'organization'):
        group_names.extend(facets.get(field_name, {}).keys())

    groups = (session.query(model.Group.name, model.Group.title)
                    .filter(model.Group.name.in_(group_names))
                    .all()
              if group_names else [])
    group_titles_by_name = dict(groups)

    # Transform facets into a more useful data structure.
    restructured_facets = {}
    for key, value in facets.items():
        restructured_facets[key] = {
            'title': key,
            'items': []
        }
        for key_, value_ in value.items():
            new_facet_dict = {}
            new_facet_dict['name'] = key_
            if key in ('groups', 'organization'):
                display_name = group_titles_by_name.get(key_, key_)
                display_name = display_name if display_name and display_name.strip() else key_
                new_facet_dict['display_name'] = display_name
            elif key == 'license_id':
                license = model.Package.get_license_register().get(key_)
                if license:
                    new_facet_dict['display_name'] = license.title
                else:
                    new_facet_dict['display_name'] = key_
            else:
                new_facet_dict['display_name'] = key_
            new_facet_dict['count'] = value_
            restructured_facets[key]['items'].append(new_facet_dict)
    search_results['search_facets'] = restructured_facets

    # check if some extension needs to modify the search results
    for item in plugins.PluginImplementations(plugins.IPackageController):
        search_results = item.after_search(search_results, data_dict)

    # After extensions have had a chance to modify the facets, sort them by
    # display name.
    for facet in search_results['search_facets']:
        search_results['search_facets'][facet]['items'] = sorted(
            search_results['search_facets'][facet]['items'],
            key=lambda facet: facet['display_name'], reverse=True)

    return search_results


@logic.side_effect_free
def resource_search(context, data_dict):

    model = context['model']

    query = data_dict.get('query')
    fields = data_dict.get('fields')

    if query is None and fields is None:
        raise ValidationError({'query': _('Missing value')})

    elif query is not None and fields is not None:
        raise ValidationError(
            {'fields': _('Do not specify if using "query" parameter')})

    elif query is not None:
        if isinstance(query, basestring):
            query = [query]
        try:
            fields = dict(pair.split(":", 1) for pair in query)
        except ValueError:
            raise ValidationError(
                {'query': _('Must be <field>:<value> pair(s)')})

    else:
        log.warning('Use of the "fields" parameter in resource_search is '
                    'deprecated.  Use the "query" parameter instead')

        # The legacy fields paramter splits string terms.
        # So maintain that behaviour
        split_terms = {}
        for field, terms in fields.items():
            if isinstance(terms, basestring):
                terms = terms.split()
            split_terms[field] = terms
        fields = split_terms

    order_by = data_dict.get('order_by')
    offset = data_dict.get('offset')
    limit = data_dict.get('limit')

    q = model.Session.query(model.Resource) \
         .join(model.Package) \
         .filter(model.Package.state == 'active') \
         .filter(model.Package.private == False) \
         .filter(model.Resource.state == 'active') \

    resource_fields = model.Resource.get_columns()
    for field, terms in fields.items():

        if isinstance(terms, basestring):
            terms = [terms]

        if field not in resource_fields:
            msg = _('Field "{field}" not recognised in resource_search.')\
                .format(field=field)

            # Running in the context of the internal search api.
            if context.get('search_query', False):
                raise search.SearchError(msg)

            # Otherwise, assume we're in the context of an external api
            # and need to provide meaningful external error messages.
            raise ValidationError({'query': msg})

        for term in terms:

            # prevent pattern injection
            term = misc.escape_sql_like_special_characters(term)

            model_attr = getattr(model.Resource, field)

            # Treat the has field separately, see docstring.
            if field == 'hash':
                q = q.filter(model_attr.ilike(unicode(term) + '%'))

            # Resource extras are stored in a json blob.  So searching for
            # matching fields is a bit trickier.  See the docstring.
            elif field in model.Resource.get_extra_columns():
                model_attr = getattr(model.Resource, 'extras')

                like = _or_(
                    model_attr.ilike(
                        u'''%%"%s": "%%%s%%",%%''' % (field, term)),
                    model_attr.ilike(
                        u'''%%"%s": "%%%s%%"}''' % (field, term))
                )
                q = q.filter(like)

            # Just a regular field
            else:
                q = q.filter(model_attr.ilike('%' + unicode(term) + '%'))

    if order_by is not None:
        if hasattr(model.Resource, order_by):
            q = q.order_by(getattr(model.Resource, order_by))

    count = q.count()
    q = q.offset(offset)
    q = q.limit(limit)

    results = []
    for result in q:
        if isinstance(result, tuple) \
                and isinstance(result[0], model.DomainObject):
            # This is the case for order_by rank due to the add_column.
            if result[0].package.extras.get("restricted", 0) == "1" and not context.get("user", None):
                continue
            results.append(result[0])
        else:
            if result.package.extras.get("restricted", 0) == "1" and not context.get("user", None):
                continue
            results.append(result)

    # If run in the context of a search query, then don't dictize the results.
    if not context.get('search_query', False):
        results = model_dictize.resource_list_dictize(results, context)

    return {'count': count,
            'results': results}


@logic.side_effect_free
def user_list(context, data_dict):
    user = context.get('user', None)
    q = model.Session.query(model.User).filter(model.User.id=='')
    if user in (None, ''):
        return q

    user = model.User.get(user)
    if user.sysadmin:
        return logic.action.get.user_list(context, data_dict)

    return q
