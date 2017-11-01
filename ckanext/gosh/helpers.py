import os
import json
import logging

import ckan.logic as l

log = logging.getLogger(__name__)

get_languages_path = lambda: os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                      'language-codes.json')
def language_options():
    '''ISO-639-1 Languages''' 
    
    languages = []
    try:
        with open(get_languages_path()) as f:
            try:
                languages = json.loads(f.read())
                log.info('Successfully loaded {} languages'.format(len(languages)))
                
            except ValueError as e:
                log.error(str(e))
                
    except IOError as e:
        log.error(str(e))
            
    return languages

def get_language_by_code(code):
    
    language = None
    try:
        with open(get_languages_path()) as f:
            try:
                languages = json.loads(f.read())
                for lang in languages:
                    
                    if lang.get('code') != code:
                        continue
                    
                    language = lang
                
            except ValueError as e:
                log.error(str(e))
                
    except IOError as e:
        log.error(str(e))
            
    return language

def get_package_version(id):
    version = 1
    try:
        _ = l.get_action('package_revision_list')({}, {'id': id})
        version = len(_)
        
    except l.NotFound:
        pass
    
    return version