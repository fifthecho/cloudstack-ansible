#!/usr/bin/env python

# (c) 2014, Jeff Moody <fifthecho@gmail.com>
#
# This file is part of Ansible,
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

#####################################################################


# Import block
import sys
import time
import os
import ConfigParser
import os.path

try:
    import json
except ImportError:
    import simplejson as json

try:
    import urllib2
    import urllib
    import hmac
    import base64
    import hashlib
    import re
    import getopt
    import argparse
    import random
    from ansible.module_utils.basic import *
except ImportError:
    print "failed=True msg='ansible required for this module'"
    sys.exit(1)

# Utility Functions

def find_json(items, item_to_find, key):
    for item in items:
        key_value = unicode(item_to_find)
        if item[key] == key_value:
            return True

def find_object(items, item_to_find):
    for item in items:
        if item.id == item_to_find:
            return True

def find_sg_name(items, item_to_find):
    for item in items:
        key_value = unicode(item_to_find)
        if item['id'] == key_value:
            return str(item['name'])

class _HelpAction(argparse._HelpAction):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        # retrieve subparsers from parser
        subparsers_actions = [
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)]
        # there will probably only be one subparser_action,
        # but better save than sorry
        for subparsers_action in subparsers_actions:
            # get all subparsers and print help
            for choice, subparser in subparsers_action.choices.items():
                print("Command '{}'".format(choice))
                print(subparser.format_help())
        parser.exit()

def process_arguments(args):
    arguments = vars(args)
    arg_copy = arguments.copy()
    for arg in arg_copy:
        if arguments[arg] is None:
            arguments.pop(arg)
    return arguments


# CloudStack Connection Functions

def read_cloudstack_ini_settings():
    ''' Reads the settings from the cloudstack.ini file '''

    config = ConfigParser.SafeConfigParser()
    cloudstack_default_ini_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cloudstack.ini')
    cloudstack_ini_path = os.environ.get('CLOUDSTACK_INI_PATH', cloudstack_default_ini_path)
    config.read(cloudstack_ini_path)

    if not config.has_section('driver'):
        raise ValueError('cloudstack.ini file must contain a [driver] section')

    if config.has_option('driver', 'access_key'):
        access_key = config.get('driver', 'access_key')
    else:
        raise ValueError('cloudstack.ini does not have an access key defined')

    if config.has_option('driver', 'secret_key'):
        secret_key = config.get('driver', 'secret_key')
    else:
        raise ValueError('cloudstack.ini does not have a secret key defined')

    if config.has_option('driver', 'url'):
        url = config.get('driver', 'url')
    else:
        raise ValueError('cloudstack.ini does not have a URL defined')

    return {'key': access_key, 'secret': secret_key, 'url': url}


def read_cloudmonkey_config_settings():
    config = ConfigParser.SafeConfigParser()
    cloudmonkey_default_config_path = os.path.join(os.path.expanduser('~'), '.cloudmonkey', 'config')
    cloudmonkey_ini_path = os.environ.get('CLOUDMONKEY_CONFIG_PATH', cloudmonkey_default_config_path)
    config.read(cloudmonkey_ini_path)
    if not config.has_section('user'):
        raise ValueError('CloudMonkey config must contain a [user] section')

    if config.has_option('user', 'apikey'):
        access_key = config.get('user', 'apikey')
    else:
        raise ValueError('CloudMonkey config does not have an apikey defined')

    if config.has_option('user', 'secretkey'):
        secret_key = config.get('user', 'secretkey')
    else:
        raise ValueError('CloudMonkey config does not have a secretkey defined')

    if not config.has_section('server'):
        raise ValueError('CloudMonkey config must contain a [server] section')

    if config.has_option('server', 'protocol'):
        url = config.get('server', 'protocol')
        url += "://"
    else:
        raise ValueError('CloudMonkey config does not have a protocol defined')

    if config.has_option('server', 'host'):
        url += config.get('server', 'host')
    else:
        raise ValueError('CloudMonkey config does not have a host defined')

    if config.has_option('server', 'port'):
        url += ":"
        url += config.get('server', 'port')
    else:
        raise ValueError('CloudMonkey config does not have a port defined')

    if config.has_option('server', 'path'):
        url += config.get('server', 'path')
    else:
        raise ValueError('CloudMonkey config does not have a path defined')

    return {'key': access_key, 'secret': secret_key, 'url': url}


def initialize_connection(instance):
    '''
    Initialize the libcloud connection to CloudStack, preferring Ansible overrides, then environment variables,
    then a local INI file, then the CloudMonkey config.
    '''
    if ('access_key' in instance) and ('secret_key' in instance):
        access_id = instance['access_key']
        secret_key = instance['secret_key']
        cloudstack_url = instance['api_url']
    elif (os.environ.get('CLOUDSTACK_ACCESS_KEY') is not None) and \
            (os.environ.get('CLOUDSTACK_SECRET_KEY') is not None) and (os.environ.get('CLOUDSTACK_URL') is not None):
        access_id = os.environ['CLOUDSTACK_ACCESS_KEY']
        secret_key = os.environ['CLOUDSTACK_SECRET_KEY']
        cloudstack_url = os.environ['CLOUDSTACK_URL']
    elif (os.environ.get('CLOUDSTACK_INI_PATH') is not None) or \
         (os.path.isfile(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cloudstack.ini'))):
        settings = read_cloudstack_ini_settings()
        access_id = settings['key']
        secret_key = settings['secret']
        cloudstack_url = settings['url']
    elif (os.environ.get('CLOUDMONKEY_CONFIG_PATH') is not None) or \
         (os.path.isfile(os.path.join(os.path.expanduser('~'), '.cloudmonkey', 'config'))):
        settings = read_cloudmonkey_config_settings()
        access_id = settings['key']
        secret_key = settings['secret']
        cloudstack_url = settings['url']
    else:
        raise ValueError('CloudStack connection parameters not specified. Please use a cloudstack.ini '
                         'or specify your URL, Access Key, and Secret Key.')
    conn_params = dict()
    conn_params['access_key'] = access_id
    conn_params['secret_key'] = secret_key
    conn_params['api_url'] = cloudstack_url
    return conn_params

# CloudStack Request Functions

def cloudstack_request(conn_params, command, args):
    args['apikey'] = conn_params['access_key']
    args['command'] = command
    args['response'] = 'json'

    params = []
    hash_params = []

    keys = sorted(args.keys())

    for k in keys:
        if isinstance(args[k], bool):
            args[k] = str(args[k]).lower()
        hash_params.append(k + '=' + urllib.quote_plus(args[k]).replace("+", "%20"))
        params.append(k + '=' + urllib.quote_plus(args[k]).replace("+", "%20").replace("%2C", ","))
    #    print k, ":", args[k]

    hashed_query = '&'.join(hash_params)
    query = '&'.join(params)

    # print params

    signature = base64.b64encode(hmac.new(
        conn_params['secret_key'],
        msg=hashed_query.lower(),
        digestmod=hashlib.sha1
    ).digest())

    query += '&signature=' + urllib.quote_plus(signature)
    # print query

    # print "Request :", conn_params['api_url'] + '?' + query

    response = urllib2.urlopen(conn_params['api_url'] + '?' + query)
    # from IPython import embed; embed()
    decoded = json.loads(response.read())

    propertyResponse = command.lower() + 'response'
    if not propertyResponse in decoded:
        if 'errorresponse' in decoded:
            raise RuntimeError("ERROR: " + decoded['errorresponse']['errortext'])
        else:
            raise RuntimeError("ERROR: Unable to parse the response")

    response = decoded[propertyResponse]
    result = re.compile(r"^list(\w+)s").match(command.lower())

    if not result is None:
        type = result.group(1)

        if type in response:
            return response[type]
        else:
            # sometimes, the 's' is kept, as in :
            # { "listasyncjobsresponse" : { "asyncjobs" : [ ... ] } }
            type += 's'
            if type in response:
                return response[type]

    return response

def main():
    instance = dict()
    connection = initialize_connection(instance)
    request_args = dict()


    arg_parser = argparse.ArgumentParser(description='Interact with Apache CloudStack.', add_help=False)
    arg_parser.add_argument('-h', '--help', action=_HelpAction, help='Help with the commands and subcommands.')

    sub_arg_parser = arg_parser.add_subparsers(dest='subparser_name')


    deploy_parser = sub_arg_parser.add_parser('deployVirtualMachine', help='Deploy a Virtual Machine')
    deploy_parser.add_argument('-s',
                               '--serviceofferingid',
                               help='The Service Offering ID to use for the VM.',
                               required=True,
                               type=str)
    deploy_parser.add_argument('-t',
                               '--templateid',
                               help='The Template ID to use for the VM.',
                               required=True,
                               type=str)
    deploy_parser.add_argument('-z',
                               '--zoneid',
                               help='The zone ID to use for the VM.',
                               required=True,
                               type=str)
    deploy_parser.add_argument('-n',
                               '--networkids',
                               help='The Network ID(s) for the VM.',
                               type=str)
    deploy_parser.add_argument('-g',
                               '--securitygroupids',
                               help='The Security Group ID(s) for the VM.',
                               type=str)
    deploy_parser.add_argument('-k',
                               '--keypair',
                               help='The SSH Keypair Name to inject in the VM.',
                               type=str)
    deploy_parser.add_argument('-u',
                               '--userdata',
                               help='The User Data to inject in the VM.',
                               type=str)
    deploy_parser.add_argument('--name',
                               help='The Instance Name for the VM. This must be unique per-zone\
                                and isn\'t recommended in Public Clouds.',
                               type=str)
    deploy_parser.add_argument('--displayname',
                               help='The Display Name for the VM.',
                               type=str)


    destroy_parser = sub_arg_parser.add_parser('destroyVirtualMachine', help='Destroy a Virtual Machine')
    destroy_parser.add_argument('-i',
                                '--id',
                                help='Instance ID to destroy.',
                                type=str,
                                required=True)


    list_zone_parser = sub_arg_parser.add_parser('listZones', help='List CloudStack Zones')


    list_template_parser = sub_arg_parser.add_parser('listTemplates', help='List CloudStack Zones')
    list_template_parser.add_argument('-f',
                                      '--filter',
                                      help='Template Filter to apply. (Default is "featured")',
                                      type=str,
                                      default='featured',
                                      dest='templatefilter')
    list_template_parser.add_argument('--hypervisor',
                                      help='List only templates of a single Hypervisor.',
                                      type=str)
    list_template_parser.add_argument('--listall',
                                      help='List all templates you are authorized to see.\
                                       Works with filters other than featured.',
                                      action='store_true')
    list_template_parser.add_argument('-z',
                                      '--zoneid',
                                      help='List only templates in a single Zone.',
                                      type=str)


    list_serviceoffering_parser = sub_arg_parser.add_parser('listServiceOfferings', help='List CloudStack Service Offerings')


    list_securitygroup_parser = sub_arg_parser.add_parser('listSecurityGroups', help='List Security Groups')


    list_network_parser = sub_arg_parser.add_parser('listNetworks', help='List Networks')
    list_network_parser.add_argument('-z',
                                     '--zoneid',
                                     help='List only networks in a single Zone.',
                                     type=str)
    list_network_parser.add_argument('-v',
                                     '--vpcid',
                                     help='List only networks in a single VPC.',
                                     type=str)

    list_virtual_machine_parser = sub_arg_parser.add_parser('listVirtualMachines', help='List Virtual Machines')
    list_virtual_machine_parser.add_argument('-z',
                                             '--zoneid',
                                             help='List only Virtual Machines in a specific Zone.',
                                             type=str)
    list_virtual_machine_parser.add_argument('-s',
                                             '--state',
                                             help='List only Virtual Machines of a specific State.',
                                             type=str)
    list_virtual_machine_parser.add_argument('-t',
                                             '--tags',
                                             help='List only Virtual Machines with a specific tag.',
                                             type=str)
    list_virtual_machine_parser.add_argument('-p',
                                             '--hypervisor',
                                             help='List only Virtual Machines on a specific Hypervisor.',
                                             type=str)
    list_virtual_machine_parser.add_argument('-n',
                                             '--networkid',
                                             help='List only Virtual Machines in a specific network.',
                                             type=str)

    for subparser in [arg_parser]:
       subparser.format_help()

    args = arg_parser.parse_args()
    if args.subparser_name == 'deployVirtualMachine':
        if args.securitygroupids is None and args.networkids is None:
            print "Either a Network or Security Group ID is required."
            exit(2)


    request_args = process_arguments(args)
    command = request_args['subparser_name']
    request_args.pop('subparser_name')

    request = cloudstack_request(connection, command, request_args)

    if command.startswith('list'):
        print json.dumps(request, indent=2, sort_keys=True)
    else:
        async_job = dict()
        if request['jobid'] is not None:
            async_job['jobid'] = request['jobid']
            job_status = cloudstack_request(connection, 'queryAsyncJobResult', async_job)
            while job_status['jobstatus'] == 0 and command == 'deployVirtualMachine':
                print ".",
                time.sleep(random.randint(2, 5))
                job_status = cloudstack_request(connection, 'queryAsyncJobResult', async_job)
                if job_status['jobstatus'] == 1 and command == 'deployVirtualMachine':
                    print " "
                    print 'Virtual Machine', job_status['jobresult']['virtualmachine']['name'], 'deployed with IP of', \
                        job_status['jobresult']['virtualmachine']['nic'][0]['ipaddress'],
                    if job_status['jobresult']['virtualmachine']['passwordenabled'] == True:
                        print 'and password of', job_status['jobresult']['virtualmachine']['password'],
                    print '.'
                else:
                    print 'ERROR! Job returned code', job_status['jobstatus'], '!'
            if command != 'deployVirtualMachine':
                print 'Job', request['jobid'], 'submitted to complete your request.'

    # from IPython import embed; embed()

main()