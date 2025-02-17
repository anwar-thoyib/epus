#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on Tue Sep  5 10:29:05 2024

@author: anwar
'''

import requests
import io
import pandas as pd
import msoffcrypto
import re
import numpy as np
import os
from datetime import datetime
import json

pd.set_option('future.no_silent_downcasting', True)

class FHIR_Base:
  KEYCLOAK_URL = ''
  REALM_NAME = ''
  CLIENT_ID = ''
  CLIENT_SECRET = ''
  FHIR_BASE_URL = ''
  bearer_token  = ''
  headers       = {}

#-----------------------------------------------------------------------------
  def __init__(self):
    self.testing        = True
    self.debug          = True
    self.delay          = 1
    self.token_filename = 'token-dev.key'
    self.base_url       = self.FHIR_BASE_URL
    if not self.bearer_token: self.read_bearer_token()

#-----------------------------------------------------------------------------
  def read_bearer_token(self, token_filename=''):
    if token_filename:
      self.token_filename = token_filename

    if os.path.isfile(self.token_filename):
      fin = open(self.token_filename)
      for line in fin.readlines():
        rline = re.search('^#', line)
        if rline: continue
        self.bearer_token = re.findall(r'^(\S+)$', line)[0]
      
      fin.close()

      self.headers = {
        'Authorization': f'Bearer {self.bearer_token}'
      }

    else:
      self.get_and_save_token()

#-----------------------------------------------------------------------------
  def get_keycloak_token(self):
    print('[info]: generate new token.')
    token_url = f'{self.KEYCLOAK_URL}/realms/{self.REALM_NAME}/protocol/openid-connect/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {
        'client_id': self.CLIENT_ID,
        'client_secret': self.CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    response = requests.post(token_url, headers=headers, data=payload)
    response.raise_for_status()
    return response.json()['access_token']

#-----------------------------------------------------------------------------
  def get_and_save_token(self):
    self.bearer_token = self.get_keycloak_token()
    fout = open(self.token_filename, 'w')
    fout.write(self.bearer_token)
    fout.close()

    self.headers = {
      'Authorization': f'Bearer {self.bearer_token}'
    }

#-----------------------------------------------------------------------------
  def fullUrl_to_reference(self, fullUrl):
    rreference = re.search(r'^'+ self.base_url +'(.+)$', fullUrl)
    if rreference:
      return rreference.group(1)
      
    return fullUrl
    
#-----------------------------------------------------------------------------
  def get_resource_by_identifier(self, resource_type, identifier):
    params = {
      'identifier': identifier
    }
  
    url      = self.base_url + resource_type
    response = requests.get(url, params=params, headers=self.headers)
  
    if response.status_code == 401:
      self.get_and_save_token()
      response = requests.get(url, params=params, headers=self.headers)

    if response.status_code != 200:
        raise Exception(f'Error: {response.status_code} - {response.text}')
  
    response_json = response.json()
  #  if response_json['total'] > 1:
  #    raise Exception(f'Error: we found more than one {resource_type} with identifier {identifier}')
  
    if 'entry' not in response_json:
      return {}, ''
  
    fullUrl = response_json['entry'][0]['fullUrl']
    reference = self.fullUrl_to_reference(fullUrl)
    
    return response_json['entry'][0]['resource'], reference
    
#-----------------------------------------------------------------------------
  def get_resource_by_reference(self, reference):
    url = f'{self.base_url}{reference}'
    response = requests.get(url, headers=self.headers)

    if response.status_code == 401:
      self.get_and_save_token()
      response = requests.get(url, headers=self.headers)

    if response.status_code == 200:
      response_json = response.json()
      return response_json
    else:
      tmp = dict()
      return tmp

#-----------------------------------------------------------------------------
  def post_bundle_transaction(self, json):
    bundle_json = {
      'resourceType': 'Bundle',
      'type': 'transaction',
      'entry': json
    }
  
    response = requests.post(self.base_url, json=bundle_json, headers=self.headers)
    
    if response.status_code == 401:
      self.get_and_save_token()
      response = requests.post(self.base_url, json=bundle_json, headers=self.headers)

    if response.status_code != 200:
      raise Exception(f'Error: {response.status_code} - {response.text}')
  
    print('  Success send transaction bundle')
      
#-----------------------------------------------------------------------------
  def update_fhir_json(self, fhir_json, update_json):
    for key, value in update_json.items():
      if key in fhir_json:
        # Handle list merging (merge arrays without duplicates)
        if isinstance(fhir_json[key], list) and isinstance(value, list):
          fhir_json[key] = self.merge_lists(fhir_json[key], value)
        # Handle nested dictionaries (recursive merge)
        elif isinstance(fhir_json[key], dict) and isinstance(value, dict):
          self.update_fhir_json(fhir_json[key], value)
        # Overwrite simple fields (non-list, non-dict)
        else:
          fhir_json[key] = value
      else:
        # If key doesn't exist in json1, add it
        fhir_json[key] = value

    return fhir_json

#-----------------------------------------------------------------------------
  def merge_lists(self, list1, list2):
    # Basic merging logic for lists (no duplicates)
    combined_list = list1[:]
    for item in list2:
      if item not in combined_list:
        combined_list.append(item)

    return combined_list
    
#-----------------------------------------------------------------------------
  def merge_nested_dicts(self, dict1, dict2):
    result = dict1.copy()

    for key, value in dict2.items():
      if key in result and isinstance(result[key], dict) and isinstance(value, dict):
        result[key] = self.merge_nested_dicts(result[key], value)
      else:
        result[key] = value

    return result

#-----------------------------------------------------------------------------
  def _build_new_resource(self, resource, updated_resource):
    if resource:
      return self.update_fhir_json(resource, updated_resource)
    else:
      return updated_resource

    
#============================================================================
class FHIR_Patient(FHIR_Base):

#-----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Patient'
    self.__method        = 'PUT'

#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method
        
#----------------------------------------------------------------------------
  def __get_updated_json(self, emr_no, patient_name):
    identifier          = emr_no
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)

    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [
        {
          'use': 'usual',
          'system': 'https://fhir.kemkes.go.id/id/ihs-number',
          'value': f'{identifier}'
        }
      ],
      'name': [{
        'use': 'official',
        'text': f'{patient_name}'
      }]
    }

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': 'urn:uuid:patient_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }
        
    print(f'  {self.__method} {self.__resource_type} {identifier}')

    return request_json
  
#----------------------------------------------------------------------------
  def get_updated_json(self, emr_no, patient_name):
    return self.__get_updated_json(emr_no, patient_name)
    
#----------------------------------------------------------------------------
  def update_fhir_data(self, emr_no, patient_name):
    request_json = self.__get_updated_json(emr_no, patient_name)
    self.post_bundle_transaction(request_json)


#============================================================================
class FHIR_Practitioner(FHIR_Base):

#-----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Practitioner'
    self.__method        = 'PUT'
        
#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, practitioner_type, practitioner_id, nama_practitioner):
    identifier          = practitioner_id
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)

    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [
        {
          'use': 'usual',
          'system': 'https://fhir.kemkes.go.id/id/nakes-his-number',
          'value': f'{identifier}'
        }
      ],
      'name': [{
        'use': 'official',
        'text': f'{nama_practitioner}'
      }]
    }

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': f'urn:uuid:practitioner_{practitioner_type}_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }
        
    print(f'  {self.__method} {self.__resource_type} {identifier}')

    return request_json
  
#----------------------------------------------------------------------------
  def get_updated_json(self, practitioner_type, practitioner_id, nama_practitioner):
    return self.__get_updated_json(practitioner_type, practitioner_id, nama_practitioner)

#----------------------------------------------------------------------------
  def update_fhir_data(self, practitioner_type, practitioner_id, nama_practitioner):
    request_json = self.__get_updated_json(practitioner_type, practitioner_id, nama_practitioner)
    self.post_bundle_transaction(request_json)


#============================================================================
class FHIR_Observation(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Observation'
    self.__method        = 'PUT'

#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan=''):
    identifier          = id_pendaftaran.replace(' ', '-')
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)
    
    indicator = ''
    if suhu         : indicator = 'suhu'
    if denyut_nadi  : indicator = 'denyut_nadi'
    if nafas        : indicator = 'nafas'
    if sistolik     : indicator = 'sistolik'
    if diastolik    : indicator = 'diastolik'
    if lingkar_perut: indicator = 'lingkar_perut'
    if tinggi_badan : indicator = 'tinggi_badan'
    if berat_badan  : indicator = 'berat_badan'
    
    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [{
        'use': 'official',
        'system': 'https://sys-ids.kemkes.go.id/observation',
        'value': f'{identifier}-{indicator}'
      }],
      'status': 'final',
      'effectiveDateTime': f'{tanggal_periksa_fisik}',
      'subject': {
        'reference': 'urn:uuid:patient_fullUrl',
        'display': f'{patient_name}',
        'type': 'Patient'
      },
      'performer' : [{
        'reference': 'urn:uuid:practitioner_periksa_fisik_fullUrl',
        'display': f'{nama_practitioner_periksa_fisik}',
        'type': 'Practitioner'
      }],
      'encounter': {
        'reference': 'urn:uuid:encounter_fullUrl',
        'type': 'Encounter'
      }
    }

    if suhu:
      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '8310-5',
          'display': 'Body temperature',
        }],
        'text': 'Suhu Badan (Celcius)'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{suhu}',
        'unit': 'C',
        'code': 'Cel',
        'system': 'http://unitsofmeasure.org'
      }
       
    if denyut_nadi:
      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '8867-4',
          'display': 'Heart rate',
        }],
        'text': 'Nadi (x/menit)'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{denyut_nadi}',
        'unit': 'beats/minute',
        'code': '/min',
        'system': 'http://unitsofmeasure.org'
      }
      
    if nafas:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'vital-signs',
          'display' : 'Vital Signs'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '9279-1',
          'display': 'Respiratory rate',
        }],
        'text': 'Respiratory Rate (x/menit)'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{nafas}',
        'unit': 'breaths/min',
        'code': '/min',
        'system': 'http://unitsofmeasure.org'
      }

    if sistolik:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'vital-signs',
          'display' : 'Vital Signs'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '8480-6',
          'display': 'Systolic blood pressure',
        }],
        'text': 'Tekanan Darah Sistolik'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{sistolik}',
        'unit': 'mm[Hg]',
        'code': 'mm[Hg]',
        'system': 'http://unitsofmeasure.org'
      }

    if diastolik:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'vital-signs',
          'display' : 'Vital Signs'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '8462-4',
          'display': 'Diastolic blood pressure',
        }],
        'text': 'Tekanan Darah Diastolik'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{diastolik}',
        'unit': 'mm[Hg]',
        'code': 'mm[Hg]',
        'system': 'http://unitsofmeasure.org'
      }

    if lingkar_perut:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'exam',
          'display' : 'Exam'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://snomed.info/sct',
          'code': '396552003',
          'display': 'Abdominal circumference',
        }],
        'text': 'Lingkar Perut'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{lingkar_perut}',
        'unit': 'cm',
        'code': 'cm',
        'system': 'http://unitsofmeasure.org'
      }

    if tinggi_badan:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'vital-signs',
          'display' : 'Vital Signs'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '8302-2',
          'display': 'Body height',
        }],
        'text': 'Tinggi badan (cm)'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{tinggi_badan}',
        'unit': 'cm',
        'code': 'cm',
        'system': 'http://unitsofmeasure.org'
      }

    if berat_badan:
      updated_resource['category'] = [{
        'coding': [{
          'system' : 'http://terminology.hl7.org/CodeSystem/observation-category',
          'code': 'vital-signs',
          'display' : 'Vital Signs'
        }]
      }]

      updated_resource['code'] = {
        'coding': [{
          'system': 'http://loinc.org',
          'code': '29463-7',
          'display': 'Body weight',
        }],
        'text': 'Berat Badan Saat Ini (Kg)'
      }

      updated_resource['valueQuantity'] = {
        'value': f'{berat_badan}',
        'unit': 'kg',
        'code': 'kg',
        'system': 'http://unitsofmeasure.org'
      }

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': f'urn:uuid:observation_{indicator}_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}-{indicator}'
      }
    }
            
    print(f'  {self.__method} {self.__resource_type} {identifier}-{indicator}')

    return request_json

#----------------------------------------------------------------------------
  def get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan=''):
    return self.__get_updated_json(id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu, denyut_nadi, nafas, sistolik, diastolik, lingkar_perut, tinggi_badan, berat_badan)

#----------------------------------------------------------------------------
  def update_fhir_data(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan=''):
    request_json = self.__get_updated_json(id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu, denyut_nadi, nafas, sistolik, diastolik, lingkar_perut, tinggi_badan, berat_badan)
    self.post_bundle_transaction(request_json)


#============================================================================
class FHIR_Location(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Location'
    self.__method        = 'PUT'
    
#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, location_id, nama_location):
    identifier          = location_id.replace(' ', '-')
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)
      
    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [{
        'use': 'usual',
        'system': 'http://sys-ids.kemkes.go.id/location',
        'value': f'{identifier}'
      }],
      'name': f'{nama_location}'
    }

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': 'urn:uuid:location_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }

    print(f'  {self.__method} {self.__resource_type} {identifier}')
        
    return request_json

#-------------------------------------------------------------------
  def get_updated_json(self, location_id, nama_location):
    return self.__get_updated_json(location_id, nama_location)
  
#----------------------------------------------------------------------------
  def update_fhir_data(self, location_id, nama_location):
    request_json = self.get_updated_json(location_id, nama_location)
    self.post_bundle_transaction(request_json)



#============================================================================
class FHIR_Encounter(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Encounter'
    self.__method        = 'PUT'
    
#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan='', location_id='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    identifier          = id_pendaftaran.replace(' ', '-')
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)
      
    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [{
        'use': 'usual',
        'system': 'http://sys-ids.kemkes.go.id/encounter',
        'value': f'{identifier}'
      }],
      'period': {
        'start': f'{encounter_date}'
      },
      'statusHistory': {
        'status': '',
        'period': {
        }
      },
      'subject': {
        'reference': 'urn:uuid:patient_fullUrl',
        'type': 'Patient'
      },
      'participant': [{
        'actor': {
          'reference': 'urn:uuid:practitioner_fullUrl',
          'type': 'Practitioner'
        }
      }],
      'reasonReference': [
      ],
      'location': [{
        'location': {
        }
      }],
      'diagnosis': {
        'condition': [],
        'use': {
          'coding': [{
            'system': 'https://www.hl7.org/fhir/Codesystem-diagnosis-role',
            'code': 'DD',
            'display': 'Discharge diagnosis'
          }]
        }
      },
      'actualPeriod': {
        'start': f'{period_start}',
        'end': f'{period_end}'
      },
      'serviceProvider': {
        'reference': 'urn:uuid:organization_fullUrl',
        'type': 'Organization'
      }
    }
    
    if location_id: 
      updated_resource['location'][0]['location']['reference'] = 'urn:uuid:location_fullUrl'
      updated_resource['location'][0]['location']['type'] = 'Location'
    
    if history_inprogress_start_period or history_inprogress_end_period:
      updated_resource['statusHistory']['status'] = 'arrived'
      updated_resource['statusHistory']['period'] = {
          'start': f'{history_arrived_start_period}',
          'end': f'{history_arrived_end_period}'
        }
      
    if history_arrived_start_period or history_arrived_end_period:
      updated_resource['statusHistory']['status'] = 'in-progress'
      updated_resource['statusHistory']['period'] = {
          'start': f'{history_arrived_start_period}',
          'end': f'{history_arrived_end_period}'
        }

    if history_finished_start_period or history_finished_end_period:
      updated_resource['statusHistory']['status'] = 'finished'
      updated_resource['statusHistory']['period'] = {
          'start': f'{history_finished_start_period}',
          'end': f'{history_finished_end_period}'
        }

    if icdx_primer:
      condition = dict()
      condition['reference'] = 'urn:uuid:condition_fullUrl'
      condition['type'] = 'Condition'
      condition['display'] = nama_icdx_primer
      
      updated_resource['diagnosis']['condition'].append(condition)
      updated_resource['diagnosis']['rank'] = 1

    if icdx_sekunder:
      condition = dict()
      condition['reference'] = 'urn:uuid:condition_fullUrl'
      condition['type'] = 'Condition'
      condition['display'] = nama_icdx_sekunder
      
      updated_resource['diagnosis']['condition'].append(condition)
      updated_resource['diagnosis']['rank'] = 2

    if suhu:
      reference = {
        'reference': 'urn:uuid:observation_suhu_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if denyut_nadi:
      reference = {
        'reference': 'urn:uuid:observation_denyut_nadi_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if nafas:
      reference = {
        'reference': 'urn:uuid:observation_nafas_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if sistolik:
      reference = {
        'reference': 'urn:uuid:observation_sistolik_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if diastolik:
      reference = {
        'reference': 'urn:uuid:observation_diastolik_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if lingkar_perut:
      reference = {
        'reference': 'urn:uuid:observation_lingkar_perut_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if tinggi_badan:
      reference = {
        'reference': 'urn:uuid:observation_tinggi_badan_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)

    if berat_badan:
      reference = {
        'reference': 'urn:uuid:observation_berat_badan_fullUrl',
        'type': 'Observation'
      }
      
      updated_resource['reasonReference'].append(reference)


    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': 'urn:uuid:encounter_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }

    print(f'  {self.__method} {self.__resource_type} {identifier}')
        
    return request_json

#-------------------------------------------------------------------
  def get_updated_json(self, id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan='', location_id='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    return self.__get_updated_json(id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu, denyut_nadi, nafas, sistolik, diastolik, lingkar_perut, tinggi_badan, berat_badan, location_id, icdx_primer, nama_icdx_primer, icdx_sekunder, nama_icdx_sekunder)
  
#----------------------------------------------------------------------------
  def update_fhir_data(self, id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu='', denyut_nadi='', nafas='', sistolik='', diastolik='', lingkar_perut='', tinggi_badan='', berat_badan='', location_id='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    request_json = self.get_updated_json(id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu, denyut_nadi, nafas, sistolik, diastolik, lingkar_perut, tinggi_badan, berat_badan, location_id, icdx_primer, nama_icdx_primer, icdx_sekunder, nama_icdx_sekunder)
    self.post_bundle_transaction(request_json)


#============================================================================
class FHIR_Organization(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Organization'
    self.__method        = 'PUT'

#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, organization_id):
    identifier          = str(organization_id).replace(' ', '-')
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)
      
    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [ {
        'use': 'official',
        'system': f'https://fhir.kemkes.go.id/id/{identifier}',
        'value': f'{identifier}'
      }]
    }
    
    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': 'urn:uuid:organization_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }
        
    print(f'  {self.__method} {self.__resource_type} {identifier}')

    return request_json

#----------------------------------------------------------------------------
  def get_updated_json(self, organization_id):
    return self.__get_updated_json(organization_id)

#----------------------------------------------------------------------------
  def update_fhir_data(self, organization_id):
    request_json = self.__get_updated_json(organization_id)
    self.post_bundle_transaction(request_json)


#============================================================================
class FHIR_Condition(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'Condition'
    self.__method        = 'PUT'

#----------------------------------------------------------------------------
  def __get_updated_json(self, condition_type, id_pendaftaran, tanggal, patient_name, nama_practitioner, keluhan='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    identifier          = id_pendaftaran.replace(' ', '-')
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)

    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [{
        'use': 'official',
        'system': 'https://sys-ids.kemkes.go.id/condition',
        'value': f'{identifier}'
      }],
      'status': 'active',
      'clinicalStatus': {
        'system': 'http://terminology.hl7.org/CodeSystem/condition-clinical',
        'code': 'active',
        'display': 'Active'
      },      
      'category': [{
        'coding':[{
          'system': 'http://terminology.hl7.org/CodeSystem/condition-category'
        }]
      }],
      'code': {
        'coding': []
      },
      'subject': {
        'reference': 'urn:uuid:patient_fullUrl',
        'type': 'Patient',
        'display': f'{patient_name}'
      },
      'recorder': {
      },
      'participant': [{
          'reference': f'urn:uuid:practitioner_{condition_type}_fullUrl',
          'type': 'Practitioner',
          'display': f'{nama_practitioner}'
        }
      ],
      'encounter': {
        'reference': 'urn:uuid:encounter_fullUrl',
        'type': 'Encounter'
      },
      'recordedDate': f'{tanggal}',
      'note': {
        'text': f'{keluhan}'
      }
    }
    
    if condition_type == 'anamnesis':
      updated_resource['category'][0]['coding'][0]['code'] = 'problem-list-item'
      updated_resource['category'][0]['coding'][0]['display'] = 'Problem List Item'
      
      if icdx_primer:
        icdx_primer_coding = dict()
        icdx_primer_coding['system'] = 'http://hl7.org/fhir/sid/icd-10'
        icdx_primer_coding['code'] = f'{icdx_primer}'
        icdx_primer_coding['display'] = f'{nama_icdx_primer}'
        
        updated_resource['code']['coding'].append(icdx_primer_coding)
        
      if icdx_sekunder:
        icdx_sekunder_coding = dict()
        icdx_sekunder_coding['system'] = 'http://hl7.org/fhir/sid/icd-10'
        icdx_sekunder_coding['code'] = f'{icdx_sekunder}'
        icdx_sekunder_coding['display'] = f'{nama_icdx_sekunder}'
  
        updated_resource['code']['coding'].append(icdx_sekunder_coding)
  
#      if nama_practitioner_anamnesa:
#        updated_resource['recorder']['reference'] = 'urn:uuid:practitioner_anamnesa_fullUrl'
#        updated_resource['recorder']['type']      = 'Practitioner'
#        updated_resource['recorder']['display']   = nama_practitioner_anamnesa
#  
#        practitioner_anamnesa = dict()
#        practitioner_anamnesa['reference'] = 'urn:uuid:practitioner_anamnesa_fullUrl'
#        practitioner_anamnesa['type']      = 'Practitioner'
#        practitioner_anamnesa['display']   = nama_practitioner_anamnesa
#    
#        updated_resource['participant'].append(practitioner_anamnesa)
      
    if condition_type == 'diagnosis':
      updated_resource['category'][0]['coding'][0]['code'] = 'encounter-diagnosis'
      updated_resource['category'][0]['coding'][0]['display'] = 'Encounter Diagnosis'
          
      updated_resource['recorder']['reference'] = 'urn:uuid:practitioner_diagnosis_fullUrl'
      updated_resource['recorder']['type']      = 'Practitioner'
      updated_resource['recorder']['display']   = nama_practitioner

      practitioner_diagnosis = dict()
      practitioner_diagnosis['reference'] = 'urn:uuid:practitioner_diagnosis_fullUrl'
      practitioner_diagnosis['type']      = 'Practitioner'
      practitioner_diagnosis['display']   = nama_practitioner
  
      updated_resource['participant'].append(practitioner_diagnosis)

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': 'urn:uuid:condition_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}'
      }
    }
        
    print(f'  {self.__method} {self.__resource_type} {identifier}')

    return request_json

#-------------------------------------------------------------------
  def get_updated_json(self, condition_type, id_pendaftaran, tanggal, patient_name, nama_practitioner, keluhan='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    return self.__get_updated_json(condition_type, id_pendaftaran, tanggal, patient_name, nama_practitioner, keluhan, icdx_primer, nama_icdx_primer, icdx_sekunder, nama_icdx_sekunder)
  
#----------------------------------------------------------------------------
  def update_fhir_data(self, condition_type, id_pendaftaran, tanggal, patient_name, nama_practitioner, keluhan='', icdx_primer='', nama_icdx_primer='', icdx_sekunder='', nama_icdx_sekunder=''):
    request_json = self.get_updated_json(condition_type, id_pendaftaran, tanggal, patient_name, nama_practitioner, keluhan, icdx_primer, nama_icdx_primer, icdx_sekunder, nama_icdx_sekunder)
    self.post_bundle_transaction(request_json)
    


#============================================================================
class FHIR_AllergyIntolerance(FHIR_Base):

#----------------------------------------------------------------------------
  def __init__(self):
    FHIR_Base.__init__(self)
    self.__resource_type = 'AllergyIntolerance'
    self.__method        = 'PUT'
    
#-------------------------------------------------------------------
  def _set_method(self, method='PUT'):
    self.__method = method

#----------------------------------------------------------------------------
  def __get_updated_json(self, id_pendaftaran, alergi):
    identifier          = id_pendaftaran.replace(' ', '-')
    alergi              = alergi.capitalize()
    resource, reference = self.get_resource_by_identifier(self.__resource_type, identifier)
    
    allergy_text  = ''
    allergy_value = ''
    allergy_type  = ''
    
    rallergy = re.search(r'^(\w+)\s*:\s*(.+)$', alergi)
    if rallergy:
      allergy_text  = rallergy.group(1)
      allergy_value = rallergy.group(2)
      
    if allergy_text == 'Obat'   : allergy_type = 'medication'
    if allergy_text == 'Makanan': allergy_type = 'food'
    if allergy_text == 'Umum'   : allergy_type = 'environment'
    
    updated_resource = {
      'resourceType': f'{self.__resource_type}',
      'identifier': [{
        'use': 'official',
        'system': f'https://sys-ids.kemkes.go.id/allergyintolerance-{allergy_type}',
        'value': f'{identifier}-{allergy_type}'
      }],
      'patient': {
        'reference': 'urn:uuid:patient_fullUrl',
        'type': 'Patient'
      },
      'participant': [{
        'actor': {
          'reference': 'urn:uuid:practitioner_fullUrl',
          'type': 'Practitioner'
        },
        'individual': {
          'reference': 'urn:uuid:patient_fullUrl',
          'type': 'Patient'
        }
      }],
      'clinicalStatus': {
        'coding': [{
          'system': 'http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical',
          'code': 'active',
          'display': 'Active'
        }]
      },
      'code': {
        'text': f'Alergi: {allergy_value}'
      },
      'encounter': {
        'reference': 'urn:uuid:encounter_fullUrl',
        'type': 'Encounter'
      }
    }
    
    if alergi == 'Obat':
      updated_resource['category'] = [{
        'coding': [{
          'system': 'http://hl7.org/fhir/allergy-intolerance-category', 
          'code': 'medication',
          'display': 'Medication'
        }]
      }]
      
    if alergi == 'Makanan':      
      updated_resource['category'] = [{
        'coding': [{
          'system': 'http://hl7.org/fhir/allergy-intolerance-category', 
          'code': 'food',
          'display': 'Food'
        }]
      }]

    if alergi == 'Umum':
      updated_resource['category'] = [{
        'coding': [{
          'system': 'http://hl7.org/fhir/allergy-intolerance-category', 
          'code': 'environment',
          'display': 'Environment'
        }]
      }]

    new_resource = self._build_new_resource(resource, updated_resource)

    request_json = {
      'fullUrl': f'urn:uuid:allergyIntolerance_{allergy_type}_fullUrl',
      'resource': new_resource,
      'request': {
        'method': f'{self.__method}',
        'url': f'{self.__resource_type}?identifier={identifier}-{allergy_type}'
      }
    }
        
    print(f'  {self.__method} {self.__resource_type} {identifier}-{allergy_type}')

    return request_json

#-------------------------------------------------------------------
  def get_updated_json(self, id_pendaftaran, alergi):
    return self.__get_updated_json(id_pendaftaran, alergi)
  
#----------------------------------------------------------------------------
  def update_fhir_data(self, id_pendaftaran, alergi):
    request_json = self.get_updated_json(id_pendaftaran, alergi)
    self.post_bundle_transaction(request_json)    


#===========================================================================
class decrypt_Excel:

  passwd = 'XKjitAEhWBWM7nn'

#----------------------------------------------------------------------------
  def __init__(self):
    self.directory = ''
    self.filename = ''
    self.decrypted_workbook = io.BytesIO()
    self.path = ''
    self.sheet_name_list = []
    
    self.df_headers = ['ID_Pendaftaran', 'EMR_No', 'Patient_Name', 'Payment_Type', 'Encounter_Date', 'History_Arrived_start_period', 'History_Arrived_end_period', 'History_Inprogress_start_period', 'History_Inprogress_end_period', 'History_Finished_start_period', 'History_Finished_end_period', 'Period_Start', 'Period_End', 'Location_ID', 'Nama_Location', 'Practitioner_ID_Anamnesa', 'Nama_Practitioner_Anamnesa', 'Tanggal_Anamnesa', 'Keluhan', 'Alergi', 'Practitioner_ID_Periksa_Fisik', 'Nama_Practitioner_Periksa_Fisik', 'Tanggal_Periksa_Fisik', 'Suhu', 'Denyut_Nadi', 'Nafas', 'Sistolik', 'Diastolik', 'Lingkar_Perut', 'Tinggi_Badan', 'Berat_Badan', 'Practitioner_ID_Diagnosis', 'Nama_Practitioner_Diagnosis', 'Tanggal_Diagnosis', 'ICDX_Primer', 'Nama_ICDX_Primer', 'ICDX_Sekunder', 'Nama_ICDX_Sekunder', 'Organization_ID']

#-------------------------------------------------------------------
  def set_directory(self, directory):
    if directory:
      self.directory = directory
      self.path = os.path.join(self.directory, self.filename)

#-------------------------------------------------------------------
  def set_filename(self, filename):
    if filename:
      self.filename = filename
      self.path = os.path.join(self.directory, self.filename)

#-------------------------------------------------------------------
  def set_df_headers(self, headers):
    self.df_headers = headers
 
#------------------------------------------------------------------
  def open_excel_file(self, directory='', filename=''):
    self.set_directory(directory)
    self.set_filename(filename)
      
    with open(self.path, 'rb') as file:
      office_file = msoffcrypto.OfficeFile(file)
      office_file.load_key(password=self.passwd)
      office_file.decrypt(self.decrypted_workbook)
    
    workbook = pd.ExcelFile(self.decrypted_workbook)
    self.sheet_name_list = workbook.sheet_names
 
  
#============================================================================
class epus_Kunjungan(FHIR_Patient, FHIR_Practitioner, FHIR_Encounter, FHIR_Observation, FHIR_Condition, FHIR_AllergyIntolerance, FHIR_Location, FHIR_Organization, decrypt_Excel):
  
#----------------------------------------------------------------------------
  def __init__(self):
    decrypt_Excel.__init__(self)
    FHIR_Patient.__init__(self)
    FHIR_Practitioner.__init__(self)
    FHIR_Observation.__init__(self)
    FHIR_Condition.__init__(self)
    FHIR_AllergyIntolerance.__init__(self)
    FHIR_Location.__init__(self)
    FHIR_Organization.__init__(self)    
    FHIR_Encounter.__init__(self)

#-------------------------------------------------------------------
  def set_method(self, method='PUT'):
    FHIR_Encounter._set_method(method)
    FHIR_Observation._set_method(method)
    FHIR_Condition._set_method(method)
    FHIR_AllergyIntolerance._set_method(method)
    
#-------------------------------------------------------------------
  def json_to_fhir(self, data=dict()):
    id_pendaftaran                  = data['id_pendaftaran']
    emr_no                          = data['emr_no']
    patient_name                    = data['patient_name']
    payment_type                    = data['payment_type']
    encounter_date                  = data['encounter_date']
    history_arrived_start_period    = data['history_arrived_start_period']
    history_arrived_end_period      = data['history_arrived_end_period']
    history_inprogress_start_period = data['history_inprogress_start_period']
    history_inprogress_end_period   = data['history_inprogress_end_period']
    history_finished_start_period = ''
    if 'history_finished_start_period' in data: history_finished_start_period = data['history_finished_start_period']
    history_finished_end_period = ''
    if 'history_finished_end_period'in data: history_finished_end_period = data['history_finished_end_period']
    period_start = ''
    if 'period_start' in data: period_start = data['period_start']
    period_end = ''
    if 'period_end' in data: period_end = data['period_end']
    location_id = ''
    if 'location_id' in data: location_id = data['location_id']
    nama_location = ''
    if 'nama_location' in data: nama_location = data['nama_location']
    practitioner_id_anamnesa = ''
    if 'practitioner_id_anamnesa' in data: practitioner_id_anamnesa = data['practitioner_id_anamnesa']
    nama_practitioner_anamnesa = ''
    if 'nama_practitioner_anamnesa' in data: nama_practitioner_anamnesa = data['nama_practitioner_anamnesa']
    tanggal_anamnesa = ''
    if 'tanggal_anamnesa' in data: tanggal_anamnesa = data['tanggal_anamnesa']
    keluhan = ''
    if 'keluhan' in data: keluhan = data['keluhan']
    alergi = ''
    if 'alergi' in data: alergi = data['alergi']
    practitioner_id_periksa_fisik = ''
    if 'practitioner_id_periksa_fisik' in data: practitioner_id_periksa_fisik = data['practitioner_id_periksa_fisik']
    nama_practitioner_periksa_fisik = ''
    if 'nama_practitioner_periksa_fisik' in data: nama_practitioner_periksa_fisik = data['nama_practitioner_periksa_fisik']
    tanggal_periksa_fisik = ''
    if 'tanggal_periksa_fisik' in data: tanggal_periksa_fisik = data['tanggal_periksa_fisik']
    suhu = ''
    if 'suhu' in data: suhu = data['suhu']
    denyut_nadi = ''
    if 'denyut_nadi' in data: denyut_nadi = data['denyut_nadi']
    nafas = ''
    if 'nafas' in data: nafas = data['nafas']
    sistolik = ''
    if 'sistolik' in data: sistolik = data['sistolik']
    diastolik = ''
    if 'diastolik' in data: diastolik = data['diastolik']
    lingkar_perut = ''
    if 'lingkar_perut' in data: lingkar_perut = data['lingkar_perut']
    tinggi_badan = ''
    if 'tinggi_badan' in data: tinggi_badan = data['tinggi_badan']
    berat_badan = ''
    if 'berat_badan' in data: berat_badan = data['berat_badan']
    practitioner_id_diagnosis = ''
    if 'practitioner_id_diagnosis' in data: practitioner_id_diagnosis = data['practitioner_id_diagnosis']
    nama_practitioner_diagnosis = ''
    if 'nama_practitioner_diagnosis' in data: nama_practitioner_diagnosis = data['nama_practitioner_diagnosis']
    tanggal_diagnosis = ''
    if 'tanggal_diagnosis' in data: tanggal_diagnosis = data['tanggal_diagnosis']
    icdx_primer = ''
    if 'icdx_primer' in data: icdx_primer = data['icdx_primer']
    nama_icdx_primer = ''
    if 'nama_icdx_primer' in data: nama_icdx_primer = data['nama_icdx_primer']
    icdx_sekunder = ''
    if 'icdx_sekunder' in data: icdx_sekunder = data['icdx_sekunder']
    nama_icdx_sekunder = ''
    if 'nama_icdx_sekunder' in data: nama_icdx_sekunder = data['nama_icdx_sekunder']
    organization_id = ''
    if 'organization_id' in data: organization_id = data['organization_id']

    json_patient   = FHIR_Patient.get_updated_json(self, emr_no, patient_name)
        
    json_data = [
      json_patient
    ]
    
    json_encounter = FHIR_Encounter.get_updated_json(self, id_pendaftaran, encounter_date, history_arrived_start_period, history_arrived_end_period, history_inprogress_start_period, history_inprogress_end_period, history_finished_start_period, history_finished_end_period, period_start, period_end, suhu, denyut_nadi, nafas, sistolik, diastolik, lingkar_perut, tinggi_badan, berat_badan, location_id, icdx_primer, nama_icdx_primer, icdx_sekunder, nama_icdx_sekunder)

    alergi_list = alergi.split('|')
    for element in alergi_list:
      element = element.capitalize()
      json_allergy_intolerance = FHIR_AllergyIntolerance.get_updated_json(self, id_pendaftaran, element)
      json_data.append(json_allergy_intolerance)
          
    if practitioner_id_anamnesa:
      json_practitioner_anamnesa = FHIR_Practitioner.get_updated_json(self, 'anamnesa', practitioner_id_anamnesa, nama_practitioner_anamnesa)
      json_data.append(json_practitioner_anamnesa)

      json_condition_anamesa = FHIR_Condition.get_updated_json(self, 'anamnesa', id_pendaftaran, tanggal_anamnesa, patient_name, nama_practitioner_anamnesa, keluhan=keluhan)
      json_data.append(json_condition_anamesa)
      
    if practitioner_id_periksa_fisik:
      json_practitioner_periksa_fisik = FHIR_Practitioner.get_updated_json(self, 'periksa_fisik', practitioner_id_periksa_fisik, nama_practitioner_periksa_fisik)
      json_data.append(json_practitioner_periksa_fisik)

      if suhu: 
        json_observation_suhu = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, suhu=suhu)
        json_data.append(json_observation_suhu)

      if denyut_nadi: 
        json_observation_denyut_nadi = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, denyut_nadi=denyut_nadi)
        json_data.append(json_observation_denyut_nadi)

      if nafas: 
        json_observation_nafas = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, nafas=nafas)
        json_data.append(json_observation_nafas)
        
      if sistolik: 
        json_observation_sistolik = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, sistolik=sistolik)
        json_data.append(json_observation_sistolik)

      if diastolik: 
        json_observation_diastolik = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, diastolik=diastolik)
        json_data.append(json_observation_diastolik)
        
      if lingkar_perut: 
        json_observation_lingkar_perut  = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, lingkar_perut=lingkar_perut)
        json_data.append(json_observation_lingkar_perut)
        
      if tinggi_badan: 
        json_observation_tinggi_badan = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, tinggi_badan=tinggi_badan)
        json_data.append(json_observation_tinggi_badan)
        
      if berat_badan:
        json_observation_berat_badan = FHIR_Observation.get_updated_json(self, id_pendaftaran, patient_name, nama_practitioner_periksa_fisik, tanggal_periksa_fisik, berat_badan=berat_badan)
        json_data.append(json_observation_berat_badan)

      if location_id:
        json_location = FHIR_Location.get_updated_json(self, location_id, nama_location)
        json_data.append(json_location)
        
      if organization_id:
        json_organization = FHIR_Organization.get_updated_json(self, organization_id)
        json_data.append(json_organization)

    if not organization_id:  del json_encounter['resource']['serviceProvider']

    json_data.append(json_encounter)

    if practitioner_id_diagnosis:
      json_practitioner_diagnosis = FHIR_Practitioner.get_updated_json(self, 'diagnosis', practitioner_id_diagnosis, nama_practitioner_diagnosis)
      json_condition_diagnosis    = FHIR_Condition.get_updated_json(self, 'diagnosis', id_pendaftaran, tanggal_diagnosis, patient_name, nama_practitioner_diagnosis, icdx_primer=icdx_primer, nama_icdx_primer=nama_icdx_primer, icdx_sekunder=icdx_sekunder, nama_icdx_sekunder=nama_icdx_sekunder)
      json_data.append(json_practitioner_diagnosis)
      json_data.append(json_condition_diagnosis)
     
    if not self.testing:
      self.post_bundle_transaction(json_data)
    
    if self.debug:
#      time.sleep(self.delay)
      print('  === JSON REQUEST ==========')
      print(json.dumps(json_data, indent=2))
      print('  === JSON RESOURCES ========')
      response, reference = self.get_resource_by_identifier('Patient', emr_no)
      if response: print(response)
      
      if practitioner_id_anamnesa:
        response, reference = self.get_resource_by_identifier('Practitioner', practitioner_id_anamnesa)
        if response: print(response)
      
      if practitioner_id_periksa_fisik:
        response, reference = self.get_resource_by_identifier('Practitioner', practitioner_id_periksa_fisik)
        if response: print(response)

      if practitioner_id_diagnosis:
        response, reference = self.get_resource_by_identifier('Practitioner', practitioner_id_diagnosis)
        if response: print(response)

      if suhu:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-suhu')
        if response: print(response)

      if denyut_nadi:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-denyut_nadi')
        if response: print(response)

      if nafas:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-nafas')
        if response: print(response)

      if sistolik:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-sistolik')
        if response: print(response)

      if diastolik:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-diastolik')
        if response: print(response)

      if lingkar_perut:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-lingkar_perut')
        if response: print(response)

      if tinggi_badan:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-tinggi_badan')
        if response: print(response)

      if berat_badan:
        response, reference = self.get_resource_by_identifier('Observation', f'{id_pendaftaran}-berat_badan')
        if response: print(response)

      response, reference = self.get_resource_by_identifier('Encounter', id_pendaftaran)
      if response: print(response)
      
      for element in alergi_list:
        element = element.capitalize()
        response, reference = self.get_resource_by_identifier('AllergyIntolerance', f'{id_pendaftaran}-{element}')
        if response: print(response)

      response, reference = self.get_resource_by_identifier('Condition', id_pendaftaran)
      if response: print(response)

      response, reference = self.get_resource_by_identifier('Location', location_id)
      if response: print(response)
      
      if organization_id:
        response, reference = self.get_resource_by_identifier('Organization', organization_id)
        if response: print(response)

#----------------------------------------------------------------------------
  def collect_from_excel(self, directory='', filename='', limit=0):
    self.open_excel_file(directory, filename)
    for sheet_name in self.sheet_name_list:
      df = pd.read_excel(self.decrypted_workbook, sheet_name=sheet_name)
      df_headers = df.columns.values.tolist()
      if not self.df_headers:
        print(df_headers)
        break

      if self.df_headers != df_headers:
        print('Warning: header not matches!')

      print('{no}|{id_pendaftaran}|{emr_no}|{patient_name}|{payment_type}|{encounter_date}|{history_arrived_start_period}|{history_arrived_end_period}|{history_inprogress_start_period}|{history_inprogress_end_period}|{history_finished_start_period}|{history_finished_end_period}|{period_start}|{period_end}|{location_id}|{nama_location}|{practitioner_id_anamnesa}|{nama_practitioner_anamnesa}|{tanggal_anamnesa}|{keluhan}|{alergi}|{practitioner_id_periksa_fisik}|{nama_practitioner_periksa_fisik}|{tanggal_periksa_fisik}|{suhu}|{denyut_nadi}|{nafas}|{sistolik}|{diastolik}|{lingkar_perut}|{tinggi_badan}|{berat_badan}|{practitioner_id_diagnosis}|{nama_practitioner_diagnosis}|{tanggal_diagnosis}|{icdx_primer}|{nama_icdx_primer}|{icdx_sekunder}|{nama_icdx_sekunder}|{organization_id}')

      if df.empty: return

      if limit > 0: df = df[0:limit]
      df = df.replace(np.nan, '')
      for index, row in df.iterrows():
        no                              = index + 1
        id_pendaftaran                  = row['ID_Pendaftaran']
        emr_no                          = row['EMR_No']
        patient_name                    = row['Patient_Name']
        payment_type                    = row['Payment_Type']
        encounter_date                  = row['Encounter_Date']
        history_arrived_start_period    = row['History_Arrived_start_period']
        history_arrived_end_period      = row['History_Arrived_end_period']
        history_inprogress_start_period = row['History_Inprogress_start_period']
        history_inprogress_end_period   = row['History_Inprogress_end_period']
        history_finished_start_period   = row['History_Finished_start_period']
        history_finished_end_period     = row['History_Finished_end_period']
        period_start                    = row['Period_Start']
        period_end                      = row['Period_End']
        location_id                     = row['Location_ID']
        nama_location                   = row['Nama_Location']
        practitioner_id_anamnesa        = row['Practitioner_ID_Anamnesa']
        nama_practitioner_anamnesa      = row['Nama_Practitioner_Anamnesa']
        tanggal_anamnesa                = row['Tanggal_Anamnesa']
        keluhan                         = row['Keluhan']
        alergi                          = row['Alergi']
        practitioner_id_periksa_fisik   = row['Practitioner_ID_Periksa_Fisik']
        nama_practitioner_periksa_fisik = row['Nama_Practitioner_Periksa_Fisik']
        tanggal_periksa_fisik           = row['Tanggal_Periksa_Fisik']
        suhu                            = row['Suhu']
        denyut_nadi                     = row['Denyut_Nadi']
        nafas                           = row['Nafas']
        sistolik                        = row['Sistolik']
        diastolik                       = row['Diastolik']
        lingkar_perut                   = row['Lingkar_Perut']
        tinggi_badan                    = row['Tinggi_Badan']
        berat_badan                     = row['Berat_Badan']
        practitioner_id_diagnosis       = row['Practitioner_ID_Diagnosis']
        nama_practitioner_diagnosis     = row['Nama_Practitioner_Diagnosis']
        tanggal_diagnosis               = row['Tanggal_Diagnosis']
        icdx_primer                     = row['ICDX_Primer']
        nama_icdx_primer                = row['Nama_ICDX_Primer']
        icdx_sekunder                   = row['ICDX_Sekunder']
        nama_icdx_sekunder              = row['Nama_ICDX_Sekunder']
        organization_id                 = row['Organization_ID']
        
        print(f'{no}|{id_pendaftaran}|{emr_no}|{patient_name}|{payment_type}|{encounter_date}|{history_arrived_start_period}|{history_arrived_end_period}|{history_inprogress_start_period}|{history_inprogress_end_period}|{history_finished_start_period}|{history_finished_end_period}|{period_start}|{period_end}|{location_id}|{nama_location}|{practitioner_id_anamnesa}|{nama_practitioner_anamnesa}|{tanggal_anamnesa}|{keluhan}|{alergi}|{practitioner_id_periksa_fisik}|{nama_practitioner_periksa_fisik}|{tanggal_periksa_fisik}|{suhu}|{denyut_nadi}|{nafas}|{sistolik}|{diastolik}|{lingkar_perut}|{tinggi_badan}|{berat_badan}|{practitioner_id_diagnosis}|{nama_practitioner_diagnosis}|{tanggal_diagnosis}|{icdx_primer}|{nama_icdx_primer}|{icdx_sekunder}|{nama_icdx_sekunder}|{organization_id}')

        if encounter_date                 : encounter_date                  = encounter_date.strftime('%Y-%m-%dT%H:%M:%S')
        if tanggal_anamnesa               : tanggal_anamnesa                = tanggal_anamnesa.strftime('%Y-%m-%dT%H:%M:%S')
        if tanggal_diagnosis              : tanggal_diagnosis               = tanggal_diagnosis.strftime('%Y-%m-%dT%H:%M:%S')
        if tanggal_periksa_fisik          : tanggal_periksa_fisik           = tanggal_periksa_fisik.strftime('%Y-%m-%dT%H:%M:%S')
        if history_arrived_start_period   : history_arrived_start_period    = history_arrived_start_period.strftime('%Y-%m-%dT%H:%M:%S')
        if history_arrived_end_period     : history_arrived_end_period      = history_arrived_end_period.strftime('%Y-%m-%dT%H:%M:%S')
        if history_inprogress_start_period: history_inprogress_start_period = history_inprogress_start_period.strftime('%Y-%m-%dT%H:%M:%S')
        if history_inprogress_end_period  : history_inprogress_end_period   = history_inprogress_end_period.strftime('%Y-%m-%dT%H:%M:%S')
        if history_finished_start_period  : history_finished_start_period   = history_finished_start_period.strftime('%Y-%m-%dT%H:%M:%S')
        if history_finished_end_period    : history_finished_end_period     = history_finished_end_period.strftime('%Y-%m-%dT%H:%M:%S')
        if period_start                   : period_start                    = period_start.strftime('%Y-%m-%dT%H:%M:%S')
        if period_end                     : period_end                      = period_end.strftime('%Y-%m-%dT%H:%M:%S')            

        data = dict()
        data['id_pendaftaran']                  = id_pendaftaran
        data['emr_no']                          = emr_no
        data['patient_name']                    = patient_name
        data['payment_type']                    = payment_type
        data['encounter_date']                  = encounter_date
        data['history_arrived_start_period']    = history_arrived_start_period
        data['history_arrived_end_period']      = history_arrived_end_period
        data['history_inprogress_start_period'] = history_inprogress_start_period
        data['history_inprogress_end_period']   = history_inprogress_end_period
        data['history_finished_start_period']   = history_finished_start_period
        data['history_finished_end_period']     = history_finished_end_period
        data['period_start']                    = period_start
        data['period_end']                      = period_end
        data['location_id']                     = location_id
        data['nama_location']                   = nama_location
        data['practitioner_id_anamnesa']        = practitioner_id_anamnesa
        data['nama_practitioner_anamnesa']      = nama_practitioner_anamnesa
        data['tanggal_anamnesa']                = tanggal_anamnesa
        data['keluhan']                         = keluhan
        data['alergi']                          = alergi
        data['practitioner_id_periksa_fisik']   = practitioner_id_periksa_fisik
        data['nama_practitioner_periksa_fisik'] = nama_practitioner_periksa_fisik
        data['tanggal_periksa_fisik']           = tanggal_periksa_fisik
        data['suhu']                            = suhu
        data['denyut_nadi']                     = denyut_nadi
        data['nafas']                           = nafas
        data['sistolik']                        = sistolik
        data['diastolik']                       = diastolik
        data['lingkar_perut']                   = lingkar_perut
        data['tinggi_badan']                    = tinggi_badan
        data['berat_badan']                     = berat_badan
        data['practitioner_id_diagnosis']       = practitioner_id_diagnosis
        data['nama_practitioner_diagnosis']     = nama_practitioner_diagnosis
        data['tanggal_diagnosis']               = tanggal_diagnosis
        data['icdx_primer']                     = icdx_primer
        data['nama_icdx_primer']                = nama_icdx_primer
        data['icdx_sekunder']                   = icdx_sekunder
        data['nama_icdx_sekunder']              = nama_icdx_sekunder
        data['organization_id']                 = organization_id
        
        self.json_to_fhir(data)
        
#----------------------------------------------------------------------------
  def reformat_datetime(self, datetime_str):
    rdatetime = re.search(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})$', datetime_str)
    if rdatetime:
      mydate = rdatetime.group(1)
      mytime = rdatetime.group(2)

      return f'{mydate}T{mytime}+07:00' 
    
    return datetime_str

#----------------------------------------------------------------------------
  def collect_from_csv(self, directory='', filename='', limit=0):
    self.df_headers = ['ID_Pendaftaran TEXT', 'EMR_No TEXT', 'Nama_Pasien TEXT', 'Payment_Type TEXT', 'Encounter_Date DATETIME', 'History_Arrived_start_period DATETIME', 'History_Arrived_end_period DATETIME', 'History_Inprogress_start_period DATETIME', 'History_Inprogress_end_period DATETIME', 'History_Finished_start_period DATETIME', 'History_Finished_end_period DATETIME', 'Period_Start DATETIME', 'Period_End DATETIME', 'Location_ID TEXT', 'Nama_Location TEXT', 'Practitioner_ID_Anamnesa TEXT', 'Nama_Practitioner_Anamnesa TEXT', 'Tanggal_Anamnesa DATETIME', 'Keluhan TEXT', 'Alergi TEXT', 'Practitioner_ID_Periksa_Fisik TEXT', 'Nama_Practitioner_Periksa_Fisik TEXT', 'Tanggal_Periksa_Fisik DATETIME', 'Suhu FLOAT', 'Denyut_Nadi INTEGER', 'Nafas INTEGER', 'Sistolik INTEGER', 'Diastolik INTEGER', 'Lingkar_Perut FLOAT', 'Tinggi_Badan DOUBLE', 'Berat_Badan DOUBLE', 'Practitioner_ID_Diagnosis TEXT', 'Nama_Practitioner_Diagnosis TEXT', 'Tanggal_Diagnosis DATETIME', 'ICDX_Primer TEXT', 'Nama_ICDX_Primer TEXT', 'ICDX_Sekunder TEXT', 'Nama_ICDX_Sekunder TEXT', 'Organization_ID TEXT']
    path = directory + filename
    df = pd.read_csv(path, sep=',', quotechar="'", quoting=2, na_values="NULL", on_bad_lines="warn")
    df_headers = df.columns.values.tolist()
    if not self.df_headers:
      print(df_headers)
      return

    if self.df_headers != df_headers:
      print('Warning: header not matches!')

    print('{no}|{id_pendaftaran}|{emr_no}|{patient_name}|{payment_type}|{encounter_date}|{history_arrived_start_period}|{history_arrived_end_period}|{history_inprogress_start_period}|{history_inprogress_end_period}|{history_finished_start_period}|{history_finished_end_period}|{period_start}|{period_end}|{location_id}|{nama_location}|{practitioner_id_anamnesa}|{nama_practitioner_anamnesa}|{tanggal_anamnesa}|{keluhan}|{alergi}|{practitioner_id_periksa_fisik}|{nama_practitioner_periksa_fisik}|{tanggal_periksa_fisik}|{suhu}|{denyut_nadi}|{nafas}|{sistolik}|{diastolik}|{lingkar_perut}|{tinggi_badan}|{berat_badan}|{practitioner_id_diagnosis}|{nama_practitioner_diagnosis}|{tanggal_diagnosis}|{icdx_primer}|{nama_icdx_primer}|{icdx_sekunder}|{nama_icdx_sekunder}|{organization_id}')

    if df.empty: return

    if limit > 0: df = df[0:limit]
    df = df.replace(np.nan, '')
    for index, row in df.iterrows():
      no                              = index + 1
      id_pendaftaran                  = row['ID_Pendaftaran TEXT']
      emr_no                          = row['EMR_No TEXT']
      patient_name                    = row['Nama_Pasien TEXT']
      payment_type                    = row['Payment_Type TEXT']
      encounter_date                  = row['Encounter_Date DATETIME']
      history_arrived_start_period    = row['History_Arrived_start_period DATETIME']
      history_arrived_end_period      = row['History_Arrived_end_period DATETIME']
      history_inprogress_start_period = row['History_Inprogress_start_period DATETIME']
      history_inprogress_end_period   = row['History_Inprogress_end_period DATETIME']
      history_finished_start_period   = row['History_Finished_start_period DATETIME']
      history_finished_end_period     = row['History_Finished_end_period DATETIME']
      period_start                    = row['Period_Start DATETIME']
      period_end                      = row['Period_End DATETIME']
      location_id                     = row['Location_ID TEXT']
      nama_location                   = row['Nama_Location TEXT']
      practitioner_id_anamnesa        = row['Practitioner_ID_Anamnesa TEXT']
      nama_practitioner_anamnesa      = row['Nama_Practitioner_Anamnesa TEXT']
      tanggal_anamnesa                = row['Tanggal_Anamnesa DATETIME']
      keluhan                         = row['Keluhan TEXT']
      alergi                          = row['Alergi TEXT']
      practitioner_id_periksa_fisik   = row['Practitioner_ID_Periksa_Fisik TEXT']
      nama_practitioner_periksa_fisik = row['Nama_Practitioner_Periksa_Fisik TEXT']
      tanggal_periksa_fisik           = row['Tanggal_Periksa_Fisik DATETIME']
      suhu                            = row['Suhu FLOAT']
      denyut_nadi                     = row['Denyut_Nadi INTEGER']
      nafas                           = row['Nafas INTEGER']
      sistolik                        = row['Sistolik INTEGER']
      diastolik                       = row['Diastolik INTEGER']
      lingkar_perut                   = row['Lingkar_Perut FLOAT']
      tinggi_badan                    = row['Tinggi_Badan DOUBLE']
      berat_badan                     = row['Berat_Badan DOUBLE']
      practitioner_id_diagnosis       = row['Practitioner_ID_Diagnosis TEXT']
      nama_practitioner_diagnosis     = row['Nama_Practitioner_Diagnosis TEXT']
      tanggal_diagnosis               = row['Tanggal_Diagnosis DATETIME']
      icdx_primer                     = row['ICDX_Primer TEXT']
      nama_icdx_primer                = row['Nama_ICDX_Primer TEXT']
      icdx_sekunder                   = row['ICDX_Sekunder TEXT']
      nama_icdx_sekunder              = row['Nama_ICDX_Sekunder TEXT']
      organization_id                 = row['Organization_ID TEXT']
      
      print(f'{no}|{id_pendaftaran}|{emr_no}|{patient_name}|{payment_type}|{encounter_date}|{history_arrived_start_period}|{history_arrived_end_period}|{history_inprogress_start_period}|{history_inprogress_end_period}|{history_finished_start_period}|{history_finished_end_period}|{period_start}|{period_end}|{location_id}|{nama_location}|{practitioner_id_anamnesa}|{nama_practitioner_anamnesa}|{tanggal_anamnesa}|{keluhan}|{alergi}|{practitioner_id_periksa_fisik}|{nama_practitioner_periksa_fisik}|{tanggal_periksa_fisik}|{suhu}|{denyut_nadi}|{nafas}|{sistolik}|{diastolik}|{lingkar_perut}|{tinggi_badan}|{berat_badan}|{practitioner_id_diagnosis}|{nama_practitioner_diagnosis}|{tanggal_diagnosis}|{icdx_primer}|{nama_icdx_primer}|{icdx_sekunder}|{nama_icdx_sekunder}|{organization_id}')

      if encounter_date : encounter_date = datetime.strptime(encounter_date, '%Y-%m-%d %H:%M:%S')
      if tanggal_anamnesa               : tanggal_anamnesa                = datetime.strptime(tanggal_anamnesa, '%Y-%m-%d %H:%M:%S')
      if tanggal_diagnosis              : tanggal_diagnosis               = datetime.strptime(tanggal_diagnosis, '%Y-%m-%d %H:%M:%S')
      if tanggal_periksa_fisik          : tanggal_periksa_fisik           = datetime.strptime(tanggal_periksa_fisik, '%Y-%m-%d %H:%M:%S')
      if history_arrived_start_period : history_arrived_start_period      = datetime.strptime(history_arrived_start_period, '%Y-%m-%d %H:%M:%S')
      if history_arrived_end_period     : history_arrived_end_period      = datetime.strptime(history_arrived_end_period, '%Y-%m-%d %H:%M:%S')
      if history_inprogress_start_period: history_inprogress_start_period = datetime.strptime(history_inprogress_start_period, '%Y-%m-%d %H:%M:%S')
      if history_inprogress_end_period  : history_inprogress_end_period   = datetime.strptime(history_inprogress_end_period, '%Y-%m-%d %H:%M:%S')
      if history_finished_start_period  : history_finished_start_period   = datetime.strptime(history_finished_start_period, '%Y-%m-%d %H:%M:%S')
      if history_finished_end_period    : history_finished_end_period     = datetime.strptime(history_finished_end_period, '%Y-%m-%d %H:%M:%S')
      if period_start                   : period_start                    = datetime.strptime(period_start, '%Y-%m-%d %H:%M:%S')
      if period_end                     : period_end                      = datetime.strptime(period_end, '%Y-%m-%d %H:%M:%S')

      data = dict()
      data['id_pendaftaran']                  = id_pendaftaran
      data['emr_no']                          = emr_no
      data['patient_name']                    = patient_name
      data['payment_type']                    = payment_type
      data['encounter_date']                  = encounter_date.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_arrived_start_period']    = history_arrived_start_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_arrived_end_period']      = history_arrived_end_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_inprogress_start_period'] = history_inprogress_start_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_inprogress_end_period']   = history_inprogress_end_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_finished_start_period']   = history_finished_start_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['history_finished_end_period']     = history_finished_end_period.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['period_start']                    = period_start.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['period_end']                      = period_end.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['location_id']                     = location_id
      data['nama_location']                   = nama_location
      data['practitioner_id_anamnesa']        = practitioner_id_anamnesa
      data['nama_practitioner_anamnesa']      = nama_practitioner_anamnesa
      data['tanggal_anamnesa']                = tanggal_anamnesa.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['keluhan']                         = keluhan
      data['alergi']                          = alergi
      data['practitioner_id_periksa_fisik']   = practitioner_id_periksa_fisik
      data['nama_practitioner_periksa_fisik'] = nama_practitioner_periksa_fisik
      data['tanggal_periksa_fisik']           = tanggal_periksa_fisik.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['suhu']                            = suhu
      data['denyut_nadi']                     = denyut_nadi
      data['nafas']                           = nafas
      data['sistolik']                        = sistolik
      data['diastolik']                       = diastolik
      data['lingkar_perut']                   = lingkar_perut
      data['tinggi_badan']                    = tinggi_badan
      data['berat_badan']                     = berat_badan
      data['practitioner_id_diagnosis']       = practitioner_id_diagnosis
      data['nama_practitioner_diagnosis']     = nama_practitioner_diagnosis
      data['tanggal_diagnosis']               = tanggal_diagnosis.strftime("%Y-%m-%dT%H:%M:%S+07:00")
      data['icdx_primer']                     = icdx_primer
      data['nama_icdx_primer']                = nama_icdx_primer
      data['icdx_sekunder']                   = icdx_sekunder
      data['nama_icdx_sekunder']              = nama_icdx_sekunder
      data['organization_id']                 = organization_id
      
      self.json_to_fhir(data)
  
#-------------------------------------------------------------------
  def collect_from_request(self, request):
    request_json = request.get_json(silent=True)
    data = dict()
    data['id_pendaftaran']                  = request_json['ID_Pendaftaran']
    data['emr_no']                          = request_json['EMR_No']
    data['patient_name']                    = request_json['Patient_Name']
    data['payment_type']                    = request_json['Encounter_Date']
    data['history_arrived_start_period']    = request_json['History_Arrived_start_period']
    data['history_arrived_end_period']      = request_json['History_Arrived_end_period']
    data['history_inprogress_start_period'] = request_json['History_Inprogress_start_period']
    data['history_inprogress_end_period']   = request_json['History_Inprogress_end_period']
    data['history_finished_start_period']   = request_json['History_Finished_start_period']
    data['history_finished_end_period']     = request_json['History_Finished_end_period']
    data['period_start']                    = request_json['Period_Start']
    data['period_end']                      = request_json['Period_End']
    data['location_id']                     = request_json['Location_ID']
    data['nama_location']                   = request_json['Nama_Location']
    data['practitioner_id_anamnesa']        = request_json['Practitioner_ID_Anamnesa']
    data['nama_practitioner_anamnesa']      = request_json['Nama_Practitioner_Anamnesa']
    data['tanggal_anamnesa']                = request_json['Tanggal_Anamnesa']
    data['keluhan']                         = request_json['Keluhan']
    data['alergi']                          = request_json['Alergi']
    data['practitioner_id_periksa_fisik']   = request_json['Practitioner_ID_Periksa_Fisik']
    data['nama_practitioner_periksa_fisik'] = request_json['Nama_Practitioner_Periksa_Fisik']
    data['tanggal_periksa_fisik']           = request_json['Tanggal_Periksa_Fisik']
    data['suhu']                            = request_json['Suhu']
    data['denyut_nadi']                     = request_json['Denyut_Nadi']
    data['nafas']                           = request_json['Nafas']
    data['sistolik']                        = request_json['Sistolik']
    data['diastolik']                       = request_json['Diastolik']
    data['lingkar_perut']                   = request_json['Lingkar_Perut']
    data['nama_icdx_primer']                = request_json['Nama_ICDX_Primer']
    data['icdx_sekunder']                   = request_json['ICDX_Sekunder']
    data['nama_icdx_sekunder']              = request_json['Nama_ICDX_Sekunder']
    data['organization_id']                 = request_json['Organization_ID']

    self.json_to_fhir(data)

#===========================================================================
if __name__ == '__main__':
  epus_Kunjungan_Garut = epus_Kunjungan()
  epus_Kunjungan_Garut.testing = False
  epus_Kunjungan_Garut.debug   = False
#  epus_Kunjungan_Garut.collect_from_excel('data/bayongbong_garut/', 'kunjungan_info_1.xls', 3)
  epus_Kunjungan_Garut.collect_from_csv('sql_dump/20241017/', 'P32051501012024_10_17_pelayanan_non_ranap.csv', 3)
#  epus_Kunjungan_Garut.collect_from_csv('sql_dump/20241017/', 'pelayanan_non_ranap.csv', 3)
