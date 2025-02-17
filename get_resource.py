#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on Tue Sep 10 11:30:01 2024

@author: anwar
'''
import os.path
import requests
import re
import sys
import json

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
    self.debug          = True
    self.delay          = 1
    self.method         = 'PUT'
    self.token_filename = 'token.key'
    self.base_url       = self.FHIR_BASE_URL
    self.read_bearer_token()
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
        self.bearer_token = re.findall("^(\S+)$", line)[0]
      
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
    rreference = re.search('^'+ self.base_url +'(.+)$', fullUrl)
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
    url = f"{self.base_url}{reference}"
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


#===========================================================================
if __name__ == '__main__':
  resource_type = ''
  identifier    = ''
  reference     = ''
  if len(sys.argv) > 1:
    resource_type = sys.argv[1]
    if len(sys.argv) > 2:
      identifier = sys.argv[2]
    else:
      reference = resource_type
  else:
    print('ERROR: need parameter!')
    print('cmd: get_resource.py <Patient> <identifier>')
    print('     get_resource.py <reference>')
    print('eq: get_resource.py Patient PAS20146165')
    print('    get_resource.py Patient/e2c28481-a56a-45cf-be07-82ab269cef39')
    exit(0)

  epus_Resource_Garut = FHIR_Base()
  response = ''
  if reference:
    response = epus_Resource_Garut.get_resource_by_reference(reference)
  else:
    response, reference = epus_Resource_Garut.get_resource_by_identifier(resource_type, identifier)

  print(json.dumps(response, indent=2))
