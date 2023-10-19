#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright 2015 Patrick Easters (@patrickeasters)
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: prtg
author: "Patrick Easters (@patrickeasters)"
short_description: Add/remove and pause/unpause PRTG devices
description:
   - Manage Paessler PRTG devices using its REST API (see http://kb.paessler.com/en/topic/593-how-can-i-use-the-prtg-application-programming-interface-api)
options:
  api_user:
    description:
      - PRTG user for making API calls (can be local or domain user)
    required: true
  api_passhash:
    description:
      - Passhash of API user (see https://www.paessler.com/manuals/prtg/my_account_settings)
    required: true
  prtg_url:
    description:
      - The base URL of your PRTG installation (e.g. https://prtg.example.com/)
    required: true
  device_id:
    description:
      - ID of PRTG device (one of device_name or device_id required)
    required: false
  device_name:
    description:
      - Name/host of device (one of device_name or device_id required)
    required: false
  clone_from:
    description:
      - ID of PRTG device to "clone" new device from
    required: false
  dest_group:
    description:
      - ID of PRTG group where new device will reside (will use group of cloned device by default)
    required: false
  state:
    description:
      - Whether the device exists in PRTG or not
    required: false
    choices: [ "present", "absent" ]
    default: present
  enabled:
    description:
      - Enabling a device unpauses it
      - Disabling a device pauses it
    required: false
    default: true


requirements: ["PRTG installation must be accessible from ansible client"]
'''

EXAMPLES = '''
- prtg:  prtg_url="https://prtg.example.com/" 
         api_user=ansible_api
         api_passhash=1234567890
         device_name=myhost.example.com
         clone_from=1234
         dest_group=5678
         state=present
         enabled=yes
'''

from ansible.module_utils.six.moves.urllib.parse import urlencode
try:
    import json
except ImportError:
    import simplejson as json
import xml.etree.ElementTree as ET
import re

# ===========================================
# PRTG helper methods
#

def api_call(module, path, params):
    
    # determine URL for PRTG API
    if (module.params['prtg_url']).endswith('/'):
        url = (module.params['prtg_url']).rstrip('/') + path
    else:
        url = module.params['prtg_url'] + path

    # build parameters
    params['username'] = module.params['api_user']
    params['passhash'] = module.params['api_passhash']

    data = urlencode(params)

    url = url + '?' + data

    return fetch_url(module, url, method='GET')


def validate_response(module, resp_info):
    
    if resp_info['status']:
        if resp_info['status'] == 401:
            module.fail_json(msg='Invalid API credentials')
        elif resp_info['status'] == 404:
            module.fail_json(msg='Invalid API URL')
        elif resp_info['status'] == 400:
            module.fail_json(msg='The API call could not be completed successfully')
        elif resp_info['status'] == 200:
            return 200
        elif resp_info['status'] == 302:
            return 302
    else:
        module.fail_json(msg='Unable to reach API server')

    return 0

def pause_device(module, device_id, paused):
    # set paused var for api_call
    if paused:
        pause_action = 0
    else:
        pause_action = 1

    # make the API call
    resp, info = api_call(module, '/api/pause.htm', {'id':device_id, 'pausemsg':'paused by ansible', 'action':pause_action})            
    if(validate_response(module, info) != 200):
        module.fail_json(msg='Failed to pause device')
    resp.close()

    return True


# ===========================================
# Module execution
#

def main():

    module = AnsibleModule(
        argument_spec=dict(
            api_user=dict(required=True),
            api_passhash=dict(required=True),
            prtg_url=dict(required=True),
            device_id=dict(required=False),
            device_name=dict(required=False),
            state=dict(default='present', choices=['present', 'absent']),
            enabled=dict(required=False, default=True, type='bool'),
            clone_from=dict(required=False),
            dest_group=dict(required=False),
            validate_certs = dict(default='yes', type='bool'),
        ),
        required_one_of=[['device_id', 'device_name']],
        supports_check_mode=True
    )

    device_id = module.params['device_id']
    device_name = module.params['device_name']

    # check if device exists
    if not device_id:

        # do an API call and get results
        check_resp, check_info = api_call(module, '/api/table.json', {'content':'devices', 'output':'json', 'columns':'objid,device,host,group,active', 'count':10000})
        
        if(validate_response(module, check_info) != 200):
            module.fail_json(msg='API request failed')
        check_result = json.loads( check_resp.read() )
        check_resp.close()

        # iterate through list of devices and see if we can find a match by device name or host
        for dev in check_result['devices']:
            # check by name
            if device_name.lower() in dev['device'].lower():
                device_id = dev['objid']
                break

            # check by host
            if device_name.lower() == dev['host'].lower():
                device_id = dev['objid']
                break
    # device_id is specified, so grab device info
    else:
        check_resp, check_info = api_call(module, '/api/table.json', {'content':'devices', 'output':'json', 'columns':'objid,device,host,group,active', 'filter_objid':device_id})
        if(validate_response(module, check_info) != 200):
            module.fail_json(msg='API request failed')
        check_result = json.loads( check_resp.read() )
        check_resp.close()

        # check to see if device exists
        if check_result['devices']:
            device_id = dev['objid']

    
    # setup changed variable
    dev_changed = False

    #
    # go through the various cases
    #

    # device should be present and needs to be created
    if module.params['state'] == 'present' and not device_id:
        # do some error checking
        if not module.params['clone_from']:
            module.fail_json(msg='Unable to create new device because: clone_from parameter not specified')
        
        # only change if we're not in check mode
        if not module.check_mode:
            # determine parent group
            if module.params['dest_group']:
                dest_group = module.params['dest_group']
            else:
                group_resp, group_info = api_call(module, '/api/getobjectstatus.htm', {'id':module.params['clone_from'], 'name':'group', 'show':'text'})
                if(validate_response(module, group_info) != 200):
                    module.fail_json(msg='API request failed')
                group_result = ET.fromstring( group_resp.read() )
                group_resp.close()

                if group_result[1] is not None and group_result[1].tag == 'result':
                    dest_group = group_result[1][0].attrib['thisid']
                else:
                    module.fail_json(msg='Unable to find parent group of clone_from')
            
            # create the new device
            create_resp, create_info = api_call(module, '/api/duplicateobject.htm', {'id':module.params['clone_from'], 'name':module.params['device_name'], 'host':module.params['device_name'], 'targetid':dest_group})            
            if(validate_response(module, create_info) != 200):
                module.fail_json(msg='API request failed')
            create_resp.close()

            # extract the new device ID from the URL returned by PRTG
            new_dev_re = re.compile('id%3D([0-9]+)')
            new_dev_match = new_dev_re.search(create_info['url'])
            if new_dev_match:
                new_dev_id = new_dev_match.group(1)
            else:
                module.fail_json(msg='Unable to parse new device ID from return request')

            # unpause device if desired
            if module.boolean(module.params['enabled']):
                pause_device(module, new_dev_id, paused=False)

        # set the changed flag
        dev_changed = True

    # device should be present and already exists
    elif module.params['state'] == 'present' and device_id:
        
        # change paused state if necessary
        if module.boolean(module.params['enabled']) == True and dev['active_raw'] == 0:
            if not module.check_mode:
                pause_device(module, device_id, paused=False)
            dev_changed = True
        elif module.boolean(module.params['enabled']) == False and dev['active_raw'] == -1:
            if not module.check_mode:
                pause_device(module, device_id, paused=True)
            dev_changed = True


    # device should be absent and currently exists
    elif module.params['state'] == 'absent' and device_id:
        
        # let's delete it!
        if not module.check_mode:
            del_resp, del_info = api_call(module, '/api/deleteobject.htm', {'id':device_id, 'approve':'1'})            
            if(validate_response(module, del_info) != 200):
                module.fail_json(msg='Failed to delete device')
            del_resp.close()

        dev_changed = True

    # device should be absent and is already absent
    elif module.params['state'] == 'absent' and not device_id:
        
        # no need to do anything
        pass

    
    # nothing else to see here
    module.exit_json(changed=dev_changed, )


# import module snippets
from ansible.module_utils.basic import *
from ansible.module_utils.urls import *

if __name__ == '__main__':
    main()
