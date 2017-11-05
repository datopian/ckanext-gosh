import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckanext.gosh.helpers as _helpers
import logging

log = logging.getLogger(__name__)


def tc_end_validator(key, flattened_data, errors, context):
    tc_end = flattened_data.get(key, None)
    tc_start = flattened_data.get(("tc_start",), None)
    if bool(tc_end) and not bool(tc_start):
        raise toolkit.Invalid("Please fill in both start and end dates.")
    if tc_start and tc_end:
        try:
            if int(tc_start) > int(tc_end):
                raise toolkit.Invalid(
                    "End date can not be earlier than start date.")
        except (TypeError, ValueError,) as e:
            raise toolkit.Invalid("Start date and end date must be numbers.")
    return flattened_data


class GoshPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IResourceController, inherit=True)
    plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IRoutes)
    plugins.implements(plugins.IActions)

    # IPackageController

    def after_show(self, context, pkg_dict):

        pkg_dict.update({'identifier': pkg_dict.get('id')})
        return pkg_dict

    def before_view(self, pkg_dict):

        pkg_dict.update({'identifier': pkg_dict.get('id')})
        return pkg_dict

    # IRoutes

    def before_map(self, map):
        map.redirect('/user/register', 'https://portal.rsrch.nl/',
                     _redirect_code='301 Moved Permanently')
        map.redirect('/user/reset', 'https://portal.rsrch.nl/',
                     _redirect_code='301 Moved Permanently')
        return map

    def after_map(self, map):
        return map

    # IDatasetForm

    def create_package_schema(self):
        schema = super(GoshPlugin, self).create_package_schema()
        not_empty = [toolkit.get_validator('not_empty'),
                     toolkit.get_converter('convert_to_extras')]
        defaults = [toolkit.get_validator('ignore_missing'),
                    toolkit.get_converter('convert_to_extras')]

        schema.update({
            'restricted': defaults,
            'number_of_participants': defaults,
            'url': not_empty,
            'notes': not_empty,
            'maintainer': not_empty,
            'author':not_empty,
            'human_research': defaults,
            'number_of_records': defaults,
            'spatial_coverage': defaults,
            'language': defaults,
            'tc_start': defaults,
            'tc_end': [
                toolkit.get_validator('ignore_missing'),
                toolkit.get_converter('convert_to_extras'),
                tc_end_validator
            ],
            'logo': defaults
        })
        return schema

    def update_package_schema(self):
        schema = super(GoshPlugin, self).update_package_schema()
        not_empty = [toolkit.get_validator('not_empty'),
                     toolkit.get_converter('convert_to_extras')]
        defaults = [toolkit.get_validator('ignore_missing'),
                    toolkit.get_converter('convert_to_extras')]

        schema.update({
            'restricted': defaults,
            'number_of_participants': defaults,
            'url': not_empty,
            'notes': not_empty,
            'maintainer': not_empty,
            'author': not_empty,
            'human_research': defaults,
            'number_of_records': defaults,
            'spatial_coverage': defaults,
            'language': defaults,
            'tc_start': defaults,
            'tc_end': [
                toolkit.get_validator('ignore_missing'),
                toolkit.get_converter('convert_to_extras'),
                tc_end_validator
            ],
            'logo': defaults
        })
        return schema

    def show_package_schema(self):

        schema = super(GoshPlugin, self).show_package_schema()
        not_empty = [toolkit.get_converter('convert_from_extras'),
                     toolkit.get_validator('not_empty')]
        defaults = [toolkit.get_converter('convert_from_extras'),
                    toolkit.get_validator('ignore_missing')]

        schema.update({
            'restricted': defaults,
            'number_of_participants': defaults,
            'maintainer': not_empty,
            'author': not_empty,
            'url': not_empty,
            'notes': not_empty,
            'human_research': defaults,
            'number_of_records': defaults,
            'spatial_coverage': defaults,
            'language': defaults,
            'tc_start': defaults,
            'tc_end': defaults,
            'logo': defaults
        })

        return schema

    def is_fallback(self):
        # Return True to register this plugin as the default handler for
        # package types not handled by any other IDatasetForm plugin.
        return True

    def package_types(self):
        # This plugin doesn't handle any special package types, it just
        # registers itself as the default (above).
        return []

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'gosh')

    def get_helpers(self):
        return {
            'language_options':
                _helpers.language_options,
            'get_language_by_code':
                _helpers.get_language_by_code,
            'get_package_version':
                _helpers.get_package_version
        }

    def after_show(self, context, package_dict):
        # Takes care of package_show and resource_show
        package = context.get("package", None)
        if package and package.extras.get("restricted",
                                          0) == "1" and not toolkit.c.user:
            raise toolkit.NotAuthorized
        return package_dict

    def before_search(self, search_params):
        # This takes care of package search
        fq = search_params.get("fq", "")
        if not toolkit.c.user:
            # There is no user logged in, hide the restricted datasets
            fq = fq + " -extras_restricted:1"
        search_params["fq"] = fq
        search_params["include_private"] = True
        return search_params

    def get_actions(self):
        from ckanext.gosh.actions import (package_autocomplete,
                                             package_search, resource_search,
                                             user_list)
        # We're overloading few actions to get the benefits of private and
        # restricted browsing and searching
        return {
            'package_autocomplete': package_autocomplete,
            'package_search': package_search,
            'resource_search': resource_search,
            'user_list': user_list
        }