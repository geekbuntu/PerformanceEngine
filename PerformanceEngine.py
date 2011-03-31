# Copyright (C) 2011 O. Can Bascil <ocanbascil at gmail com>
"""
PerformanceEngine
https://github.com/ocanbascil/Performance-AppEngine
==============================
    PerformanceEngine is a simple wrapper module that enables layered 
    data model storage in Google Application Engine. Its main goal is to 
    increase both application and developer performance.
    
    It can store/retrieve models using local cache, memcache or datastore.
    
    You can also retrieve results in different formats (list,key-model dict,
    key_name-model dict)

Requirements
------------
cachepy => http://appengine-cookbook.appspot.com/recipe/cachepy-faster-than-memcache-and-unlimited-quota/

License
-------
This program is release under the BSD License. You can find the full text of
the license in the LICENSE file.
"""
from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.api import datastore
from google.appengine.datastore import entity_pb

import cachepy
import logging

'''Constants for storage levels'''
DATASTORE = 'datastore'
MEMCACHE = 'memcache'
LOCAL = 'local'
ALL_LEVELS = [DATASTORE,MEMCACHE,LOCAL]

'''Constants for result types'''
LIST = 'list'
DICT = 'dict'
NAME_DICT = 'name_dict'

LOCAL_EXPIRATION = 0
MEMCACHE_EXPIRATION = 0

none_filter  = lambda dict : [k for k,v in dict.iteritems() if v is None]

def _dict_multi_get(keys,dict):
  '''Used for cascaded cache refresh operation'''
  result = []
  for key in keys:
    try:
      value = dict[key]
      if value is not None:
        result.append(value)
    except KeyError:
      pass
  return result
  
def _validate_storage(storage_list):
  for storage in storage_list:
    if storage not in ALL_LEVELS:
      raise StorageLayerError(storage)

def _key_str(param):
  '''Utility function that extracts a string key from a model or key instance'''
  try:
    return str(db._coerce_to_key(param))
  except db.BadArgumentError:
    raise KeyParameterError(param)
  
def _id_or_name(_key_str):
  key = db.Key(_key_str)
  return key.name() or str(key.id())

def _diff(list1,list2):
  '''Finds the difference of keys between 2 lists
  Used for layered model retrieval'''
  return list(set(list1)-set(list2))

def _to_list(param): 
    if not isinstance(param,list):
        result = []
        result.append(param)
    else:
        result = list(param)
    return result

def _to_dict(models):
  '''Utility method to create identifier:model dictionary'''
  result = {}
  for model in models:
    result[_key_str(model)] = model
  return result

def _serialize(models):
  '''Improve memcache performance converting to protobuf'''
  if models is None:
    return None
  elif isinstance(models, db.Model):
    # Just one instance
    return db.model_to_protobuf(models).Encode()
  else:
    # A list
    return [db.model_to_protobuf(x).Encode() for x in models]

def _deserialize(data):
  '''Improve memcache performance by converting from protobuf'''
  if data is None:
    return None
  elif isinstance(data, str):
    # Just one instance
    return db.model_from_protobuf(entity_pb.EntityProto(data))
  else:
    return [db.model_from_protobuf(entity_pb.EntityProto(x)) for x in data]

def _cachepy_get(keys):
  '''Get items with given keys from local cache
  
  Args:
    keys: String representation of db.Keys
  
  Returns:
    Dictionary of key,model pairs in which keys are 
    string representation of db.Key instances
  '''
  result = {}
  for key in keys:
    result[key] = cachepy.get(key)
  return result

def _cachepy_put(models,time = 0):
  '''Put given models to local cache in serialized form
   with expiration in seconds
  
  Args:
    models: List of models to be saved to local cache
    time: Expiration time in seconds for each model instance
  
  Returns:
    List of string representations of db.Keys 
    of the models that were put
    
    If no model is found for given key, value for that key
    in result is set to None
  '''
  to_put = _to_dict(models)
  if time == 0: #cachepy uses None as unlimited caching flag
    time = None
  
  for key, model in to_put.iteritems():
    cachepy.set(key,model,time)
  return to_put.keys()

def _cachepy_delete(keys):
  '''Delete models with given keys from local cache'''
  for key in keys: 
      cachepy.delete(key)

def _memcache_get(keys):
  '''Get items with given keys from memcache
  
  Args:
    keys: List of string representation of db.Keys
  
  Returns:
    Dictionary of key,model pairs in which keys are 
    string representation of db.Key instances
    
    If no model is found for given key, value for that key
    in result is set to None
  '''
  cache_results = memcache.get_multi(keys)
  result = {}
  for key in keys:
    try:
      result[key] = _deserialize(cache_results[key])
    except KeyError:
      result[key] = None
  return result
    
def _memcache_put(models,time = 0):
  '''Put given models to memcache in serialized form
   with expiration in seconds
  
  Args:
    models: List of models to be saved to local cache
    time: Expiration time in seconds for each model instance
  
  Returns:
    List of string representations of db.Keys 
    of the models that were put
  '''         
  to_put = _to_dict(models)
        
  for key,model in to_put.iteritems():
      to_put[key] = _serialize(model)
          
  memcache.set_multi(to_put,time)
  return to_put.keys()

def _memcache_delete(keys):
  '''Delete models with given keys from memcache'''
  memcache.delete_multi(keys)
  
class pdb(object):
  '''Wrapper class for google.appengine.ext.db with seamless cache support'''
  
  @classmethod
  def get(cls,keys,_storage = [MEMCACHE,DATASTORE],
          _memcache_refresh = True,
          _local_cache_refresh = False,
          _local_expiration = LOCAL_EXPIRATION,
          _memcache_expiration = MEMCACHE_EXPIRATION,
          _result_type=LIST,
          **kwds):
    """Fetch the specific Model instance with the given keys from 
    given storage layers in given format. 
    
    WARNING: If you try to get different model kinds with the same key
    names and use NAME_DICT as result type, you'll lose data as
    models with same key_names will overwrite each other
  
    Args:
      _storage: string or array of strings for target storage layers.
      _local_cache_refresh: Flag for refreshing local instance cache
      _memcache_refresh: Flag for refreshing memcache
      _local_expiration: Time for local cache expiration in seconds
                              Has no effect if _local_cache_refresh = False
      _memcache_expiration: Time for memcache expiration in seconds
                              Has no effect if _memcache_refresh = False
      _result_type: format of the result 
      
      Inherited:
        keys: Key within datastore entity collection to find; or string key;
          or list of Keys or string keys.
        config: datastore_rpc.Configuration to use for this request.
      
    Returns:
      if _result_type = LIST:
        If a single key was given: a Model instance associated with key
        for if it exists in the datastore, otherwise None; if a list of
        keys was given: a list whose items are either a Model instance or
        None.
      if _result_type = DICT:
        A key-model dictionary
      if _result_type = NAME_DICT
        A key_name-model dictionary / str(id)-model dictionary
        
    Raises:
      ResultTypeError: if an invalid result type is supplied
      StorageLayerError: If an invalid storage parameter is given  
      KeyParameterError: If something other than db.Key or string repr.
        of db.Key is given
    """
    _storage = _to_list(_storage)
    _validate_storage(_storage)
    
    keys = map(_key_str, _to_list(keys))
    old_keys = keys
    local_not_found = []
    memcache_not_found = []
    models = {}
    
    if LOCAL in _storage:
      models = dict(models,**_cachepy_get(keys))
      keys = none_filter(models)
      local_not_found = keys
          
    if MEMCACHE in _storage and len(keys):
      models = dict(models,**_memcache_get(keys))
      keys = none_filter(models)
      memcache_not_found = keys
    
    if DATASTORE in _storage and len(keys):
      db_results = [model for model in db.get(keys) if model is not None]
      if len(db_results):
        models  = dict(models,**_to_dict(db_results))
        
    if _local_cache_refresh:
      targets = _dict_multi_get(local_not_found, models)
      if len(targets):
        pdb.put(targets,_storage = LOCAL,
                _local_expiration = _local_expiration,**kwds)  
    
    if _memcache_refresh:
      targets = _dict_multi_get(memcache_not_found,models)
      if len(targets):  
        pdb.put(targets,_storage = MEMCACHE,
                _memcache_expiration = _memcache_expiration,**kwds)
        
    result = []    
    if _result_type == LIST:
      #Restore the order of entities   
      for key in old_keys:
        try:
          result.append(models[key])
        except KeyError:
          result.append(None)   
      #Normalized result
      if len(result) > 1:
        return result
      return result[0]
    elif _result_type == DICT:
      return models
    elif _result_type == NAME_DICT:
      result = {}
      for k,v in models.iteritems():
        result[_id_or_name(k)] = v
      return result
    else:
      raise ResultTypeError(_result_type)
        

  @classmethod
  def put(cls,models,_storage = [MEMCACHE,DATASTORE],
                      _local_expiration = LOCAL_EXPIRATION,
                      _memcache_expiration = MEMCACHE_EXPIRATION,
                       **kwds):
    '''Saves models into given storage layers and returns their keys
    
    If the models are written for the first time and they have no key names ,
    They are first written into datastore and then saved to other storage layers
    using the keys returned by datastore put() operation.
    
    Args:

      _storage: string or array of strings for target storage layers  
      _local_expiration: Time in seconds for local cache expiration for models
      _memcache_expiration: Time in seconds for memcache expiration for models
    
      Inherited:
        models: Model instance or list of Model instances.
        config: datastore_rpc.Configuration to use for this request.
    
    Returns:
      A Key or a list of Keys (corresponding to the argument's plurality).
    
    Raises:
      IdentifierNotFoundError if models has no key names 
      and are being written into cache storage only.
    
      Inherited:
        TransactionFailedError if the data could not be committed.
    '''

    keys = [] 
    models = _to_list(models)   
    _storage = _to_list(_storage)
    _validate_storage(_storage)
    
    try: 
      _to_dict(models)
    except db.NotSavedError:
      if DATASTORE in _storage:
        keys = db.put(models)
        models = db.get(keys)
        _storage.remove(DATASTORE)
        if len(_storage):
          return pdb.put(models,_storage,**kwds)
      else: 
        raise IdentifierNotFoundError() 
    
    if DATASTORE in _storage:
      keys = db.put(models)
      
    if LOCAL in _storage:
      keys = _cachepy_put(models, _local_expiration)

    if MEMCACHE in _storage:
      keys = _memcache_put(models,_memcache_expiration)
      
    return keys


  @classmethod
  def delete(cls,keys,_storage = ALL_LEVELS):
    """Delete one or more Model instances from given storage layers
  
    Args:
      _storage: string or array of strings for target storage layers
      
      Inherited:
        models: Model instance, key, key string or iterable thereof.
        config: datastore_rpc.Configuration to use for this request.
    """
    keys = map(_key_str, _to_list(keys))
    _storage = _to_list(_storage)
    _validate_storage(_storage)  
    
    if DATASTORE in _storage:
      db.delete(keys)
      
    if LOCAL in _storage:
      _cachepy_delete(keys)

    if MEMCACHE in _storage:
      _memcache_delete(keys)
  
  
  class Model(db.Model):
    '''Wrapper class for db.Model
    Adds cached storage support to common functions'''
    
    _default_delimiter = '|'
    
    def put(self,**kwds):
      """Writes this model instance to the given storage layers.
  
      Args:
         _storage: string or array of strings for target storage layers  
        _local_expiration: Time in seconds for local cache expiration for models
        _memcache_expiration: Time in seconds for memcache expiration for models       
        
        Inherited:
          config: datastore_rpc.Configuration to use for this request.
  
      Returns:
        The key of the instance (either the existing key or a new key).
  
      Raises:
        IdentifierNotFoundError if model has no key_name and being
          written into cache storage only.       
        
        Inherited:
          TransactionFailedError if the data could not be committed.
      """
      return pdb.put(self, **kwds)
    
    @classmethod
    def get(cls,keys,**kwds):
      '''Fetch a specific Model type instance from given storage 
      layers, using keys. 
      Args:
        See pdb.get
        
        Inherited:
          keys: Key within datastore entity collection to find; or string key;
            or list of Keys or string keys.
          config: datastore_rpc.Configuration to use for this request.
  
      Returns:
        See pdb.get
        
      Raises:
        KindError if any of the retreived objects are not instances of the
          type associated with call to 'get'.
      '''
      models = pdb.get(keys,**kwds)
      
      #Class kind check
      temp = models
      if isinstance(temp,dict):
        temp = dict.values()
      elif isinstance(temp, db.Model):
        temp = [temp]
      for instance in temp:
        if not(instance is None or isinstance(instance, cls)):
          raise db.KindError('Kind %r is not a subclass of kind %r' %
                          (instance.kind(), cls.kind())) 
      return models
    
    def delete(self,_storage = ALL_LEVELS):
      """Delete current instance from given storage layers
    
      Args:
        _storage: string or array of strings for target storage layers
      """
      pdb.delete(self.key(),_storage)
    
    @classmethod
    def get_by_key_name(cls,key_names, parent=None,**kwds):
      """Get instance of Model class by its key's name from the given storage layers.
      Args:
          See pdb.get
        
        Inherited:
          key_names: A single key-name or a list of key-names.
          parent: Parent of instances to get.  Can be a model or key.
      """
      try:
        parent = db._coerce_to_key(parent)
      except db.BadKeyError, e:
        raise db.BadArgumentError(str(e))
      
      key_names = _to_list(key_names)
      key_strings = [_key_str(db.Key.from_path(cls.kind(), name, parent=parent))
        for name in key_names]

      return pdb.get(key_strings,**kwds)
    
    @classmethod
    def get_by_id(cls, ids, parent=None,**kwds):
      """Get instance of Model class by id from the given storage layers.
      Args:
         See pdb.get
         
        Inherited:
          ids: A single id or a list of ids.
          parent: Parent of instances to get.  Can be a model or key.
      """
      try:
        parent = db._coerce_to_key(parent)
      except db.BadKeyError, e:
        raise db.BadArgumentError(str(e))
      
      ids = _to_list(ids)
      key_strings = [_key_str(datastore.Key.from_path(cls.kind(), id, parent=parent))
        for id in ids]
      
      return pdb.get(key_strings,**kwds)
    
    @classmethod
    def get_or_insert(cls,key_name,**kwds):
      '''Retrieve or create an instance of Model class using the given storage layers.
      
      If entity is found, it is returned and also cache layers are refreshed if the result
      isn't found in them. 
      
      If entity is not found, a new one is created an written into given storage layers.
      
      Args:
        See pdb.get
        
        Inherited:
          key_name: Key name to retrieve or create.
          **kwds: Keyword arguments to pass to the constructor of the model class
            if an instance for the specified key name does not already exist. If
            an instance with the supplied key_name and parent already exists, the
            rest of these arguments will be discarded.

      Returns:
        Existing instance of Model class with the specified key_name and parent
        or a new one that has just been created.
  
      Raises:
        TransactionFailedError if the specified Model instance could not be
        retrieved or created transactionally (due to high contention, etc).
      '''
      def txn():
        entity = cls(key_name=key_name, **kwds)
        entity.put(**kwds)
        return entity
    
      entity = cls.get_by_key_name(key_name,parent=kwds.get('parent'))
      if entity is None:
        return db.run_in_transaction(txn)
      else:
        return entity
      
    def cached_set(self,collection_name,index_expiration=300,**kwds):
      '''This function is a wrapper around back-reference functionality of 
      db.ReferenceProperty,allowing cached retrieval of models that reference 
      this entity.
      
      If a _ReferenceCacheIndex is found, a default pdb.get function is called
      Otherwise  the query is run and models are returned
      
      WARNING: Instead of a query instance, this function fetches and returns 
      the actual models, so it is advised not to use it for models that have 
      a high number of back-references.
      
      Basic Usage:
        class MainModel(pdb.Model):
          add_date = db.DateProperty(auto_now = True) 
        
        class RefModel(db.Model):
          ref = db.ReferenceProperty(reference_class=MainModel,
                                              collection_name = 'ref_set')
                                              
        model = MainModel.all().get()
        model.ref_set #models that reference this MainModel entity
        model.cached_set('ref_set') #Cached back-references
      
      Args:
        collection_name: Name of the back reference property
        index_expiration: Memcache expiration time for _ReferenceCacheIndex
        entity that'll be created for this reference set if there isn't any.
        
        See pdb.get for additional parameters
        
      Returns:
        A list of models that back reference this entity
      
      Raises:
        ReferenceSetError: If an invalid collection name is supplied
      '''
      property = getattr(self, collection_name)
      if not isinstance(property, db.Query):
        raise ReferenceSetError(collection_name)
      
      klass = self.__class__
      key_name = str(self.key())+klass._default_delimiter+collection_name
      query_cache = _ReferenceCacheIndex.get_by_key_name(key_name,
                                                         _storage=MEMCACHE)
      if query_cache:
        try:
          kwds.pop('_result_type') #Use default result for pdb.get
        except KeyError:
          pass
        keys = query_cache.ref_keys
        result =  pdb.get(keys,**kwds)
      else: 
        result = [model for model in getattr(self,collection_name)]
        _ReferenceCacheIndex.create(self,collection_name,result,index_expiration)
      return result    
    
    def log_properties(self,console=False):
      '''Log properties of an entity'''
      result = 'Logging properties for %s with identifier: %s =>' \
      %(self.__class__.kind(),_id_or_name(str(self.key())))
      for k,v in self.properties().iteritems():
        prop = '%s : %s' %(k,v.get_value_for_datastore(self))
        result += '('+prop+'),'
      if console:
        print result
      else:
        logging.info(result)

class _ReferenceCacheIndex(pdb.Model):
  '''This model is used for accessing the 'many' part of a 
  one-to-many relationship that uses db.ReferenceProperty
  through cache, instead of running a db.Query. 
  
  An instance of this class is saved into memcache
  when 'cached_set' property of a pdb.Model is called.
  '''
  ref_keys = db.ListProperty(db.Key,indexed = False)
  
  @classmethod
  def create(cls,reference,collection_name,
             models,_memcache_expiration):
    entity = cls(key_name=str(reference.key())+cls._default_delimiter+collection_name)
    entity.ref_keys = [model.key() for model in models]
    entity.put(_storage=MEMCACHE,
               _memcache_expiration = _memcache_expiration)    
    return entity

class _GqlCache(pdb.Model):
  '''This class will be used for db.GqlQuery result caching,
  not implemented yet'''
    
  def __init__(self,models,**kwds):
    self.model_string = _serialize(models)
    super(pdb.Model, self).__init__(**kwds)
    
  @classmethod
  def build_key_name(cls,*args,**kwds):
    arr = []
    arr.extend(args)
    arr = map(str,arr)
    if len(kwds):
      sorted_keys = sorted(kwds.keys())
      for key in sorted_keys:
        value = kwds[key]
        if isinstance(value, db.Model):
          value = value.key()
        arr.append(key+cls._default_delimiter+str(value))
  
    print arr
    print hash(''.join(arr))
    
  @property
  def models(self):
    return _deserialize(self.model_string)

  model_string = db.BlobProperty()
  add_time = db.DateTimeProperty(auto_now=True)

class QueryRunner(object):
  
  def __init__(self,query,*args,**kwds):
    self.query = query
    self.query.bind(*args,**kwds)
    self.key_name = _GqlCache.build_key_name(*args,**kwds)
    
  def fetch(self,limit,offset = 0,
                  _storage = ALL_LEVELS,
                  _result_type = LIST,
                  _refresh_cache = ALL_LEVELS,
                  _local_expiration=LOCAL_EXPIRATION,
                  _memcache_expiration = MEMCACHE_EXPIRATION,
                  _datastore_expiration = 0):
    
    
    pass


class ResultTypeError(Exception):
  def __init__(self,type):
    self.type = type
  def __str__(self):
    return  'Result type is invalid: %s. Valid values are "list" and "dict" and "name_dict"' %self.type
  
class ReferenceSetError(Exception):
  def __init__(self,type):
    self.type = type
  def __str__(self):
    return  'Entity does not have a reference set called "%s"' %self.type 
  
class StorageLayerError(Exception):
  def __init__(self,storage):
    self.storage = storage
  def __str__(self):
    return  'Storage layer name invalid: %s. Valid values are "local","memcache" and "datastore"' %self.storage

class KeyParameterError(Exception):
  def __init__(self,param):
    self.type = type(param)
  def __str__(self):
      return  '%s was given as function parameter, it should be db.Key,String or db.Model' %self.type
       
class IdentifierNotFoundError(Exception):
    def __str__(self):
        return  'Error trying to write models into cache without valid identifiers. Try enabling datastore write for the models or use keynames instead of IDs.'
