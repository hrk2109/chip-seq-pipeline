#!/usr/bin/env python
# input_shield 0.0.1
# Generated by dx-app-wizard.
#
# Basic execution pattern: Your app will run on a single machine from
# beginning to end.
#
# See https://wiki.dnanexus.com/Developer-Portal for documentation and
# tutorials on how to modify this file.
#
# DNAnexus Python Bindings (dxpy) documentation:
#   http://autodoc.dnanexus.com/bindings/python/current/

import os, requests, logging, re, urlparse, subprocess, requests, json, shlex
import dxpy

KEYFILE = 'keypairs.json'
DEFAULT_SERVER = 'https://www.encodeproject.org'
S3_SERVER='s3://encode-files/'
APPLET_FOLDER='/'
DATA_CACHE_PROJECT = None #if specified, look anywhere in this project for ENCFF files

logger = logging.getLogger(__name__)

def processkey(key):

	if key:
		keysf = open(KEYFILE,'r')
		keys_json_string = keysf.read()
		keysf.close()
		keys = json.loads(keys_json_string)
		logger.debug("Keys: %s" %(keys))
		key_dict = keys[key]
	else:
		key_dict = {}
	AUTHID = key_dict.get('key')
	AUTHPW = key_dict.get('secret')
	if key:
		SERVER = key_dict.get('server')
	else:
		SERVER = 'https://www.encodeproject.org/'

	if not SERVER.endswith("/"):
		SERVER += "/"

	return (AUTHID,AUTHPW,SERVER)

def encoded_get(url, AUTHID=None, AUTHPW=None):
	HEADERS = {'content-type': 'application/json'}
	if AUTHID and AUTHPW:
		response = requests.get(url, auth=(AUTHID,AUTHPW), headers=HEADERS)
	else:
		response = requests.get(url, headers=HEADERS)
	return response

def s3cp(accession, key=None):

	(AUTHID,AUTHPW,SERVER) = processkey(key)

	url = SERVER + '/search/?type=file&accession=%s&format=json&frame=embedded&limit=all' %(accession)
	#get the file object
	response = encoded_get(url, AUTHID, AUTHPW)
	logger.debug(response)

	#select your file
	f_obj = response.json()['@graph'][0]
	logger.debug(f_obj)

	#make the URL that will get redirected - get it from the file object's href property
	encode_url = urlparse.urljoin(SERVER,f_obj.get('href'))
	logger.debug("URL: %s" %(encode_url))
	logger.debug("%s:%s" %(AUTHID, AUTHPW))
	#stream=True avoids actually downloading the file, but it evaluates the redirection
	r = requests.get(encode_url, auth=(AUTHID,AUTHPW), headers={'content-type': 'application/json'}, allow_redirects=True, stream=True)
	try:
		r.raise_for_status
	except:
		logger.error('%s href does not resolve' %(f_obj.get('accession')))
	logger.debug("Response: %s", (r))

	#this is the actual S3 https URL after redirection
	s3_url = r.url
	logger.debug(s3_url)

	#release the connection
	r.close()

	#split up the url into components
	o = urlparse.urlparse(s3_url)

	#pull out the filename
	filename = os.path.basename(o.path)

	#hack together the s3 cp url (with the s3 method instead of https)
	bucket_url = S3_SERVER.rstrip('/') + o.path

	#cp the file from the bucket
	subprocess.check_call(shlex.split('aws s3 cp %s . --quiet' %(bucket_url)), stderr=subprocess.STDOUT)
	subprocess.check_call(shlex.split('ls -l %s' %(filename)))

	dx_file = dxpy.upload_local_file(filename)

	return dx_file

def resolve_project(identifier, privs='r'):
	logger.debug("In resolve_project with identifier %s" %(identifier))
	project = dxpy.find_one_project(name=identifier, level='VIEW', name_mode='exact', return_handler=True, zero_ok=True)
	if project == None:
		try:
			project = dxpy.get_handler(identifier)
		except:
			logger.error('Could not find a unique project with name or id %s' %(identifier))
			raise ValueError(identifier)
	logger.debug('Project %s access level is %s' %(project.name, project.describe()['level']))
	if privs == 'w' and project.describe()['level'] == 'VIEW':
		logger.error('Output project %s is read-only' %(identifier))
		raise ValueError(identifier)
	return project

def resolve_folder(project, identifier):
	if not identifier.startswith('/'):
		identifier = '/' + identifier
	try:
		project_id = project.list_folder(identifier)
	except:
		try:
			project_id = project.new_folder(identifier, parents=True)
		except:
			logger.error("Cannot create folder %s in project %s" %(identifier, project.name))
			raise ValueError('%s:%s' %(project.name, identifier))
		else:
			logger.info("New folder %s created in project %s" %(identifier, project.name))
	return identifier


def resolve_accession(accession, key):
	logger.debug("Looking for accession %s" %(accession))
	
	if not re.match(r'''^ENCFF\d{3}[A-Z]{3}''', accession):
		logger.warning("%s is not a valid accession format" %(accession))
		return None

	if DATA_CACHE_PROJECT:
		logger.debug('Looking for cache project %s' %(DATA_CACHE_PROJECT))
		try:
			project_handler = resolve_project(DATA_CACHE_PROJECT)
			snapshot_project = project_handler
		except:
			logger.error("Cannot find cache project %s" %(DATA_CACHE_PROJECT))
			snapshot_project = None

		logger.debug('Cache project: %s' %(snapshot_project))

		if snapshot_project:
			try:
				accession_search = accession + '*'
				logger.debug('Looking recursively for %s in %s' %(accession_search, snapshot_project.name))
				file_handler = dxpy.find_one_data_object(
					name=accession_search, name_mode='glob', more_ok=False, classname='file', recurse=True, return_handler=True,
					folder='/', project=snapshot_project.get_id())
				logger.debug('Got file handler for %s' %(file_handler.name))
				return file_handler
			except:
				logger.debug("Cannot find accession %s in project %s" %(accession, snapshot_project))

	# we're here because we couldn't find the cache or couldn't find the file in the cache, so look in AWS
	
	dx_file = s3cp(accession, key) #this returns a link to the file in the applet's project context

	if not dx_file:
		logger.warning('Cannot find %s.  Giving up.' %(accession))
		return None
	else:
		return dx_file

def resolve_file(identifier, key):
	logger.debug("resolve_file: %s" %(identifier))

	if not identifier:
		return None

	m = re.match(r'''^([\w\-\ \.]+):([\w\-\ /\.]+)''', identifier)
	if m: #fully specified with project:path
		project_identifier = m.group(1)
		file_identifier = m.group(2)
	else:
		logger.debug("Defaulting to the current project")
		project_identifier = dxpy.WORKSPACE_ID
		file_identifier = identifier    

	project = resolve_project(project_identifier)
	logger.debug("Got project %s" %(project.name))
	logger.debug("Now looking for file %s" %(file_identifier))

	m = re.match(r'''(^[\w\-\ /\.]+)/([\w\-\ \.]+)''', file_identifier)
	if m:
		folder_name = m.group(1)
		if not folder_name.startswith('/'):
			folder_name = '/' + folder_name
		file_name = m.group(2)
	else:
		folder_name = '/'
		file_name = file_identifier

	logger.debug("Looking for file %s in folder %s" %(file_name, folder_name))

	try:
		file_handler = dxpy.find_one_data_object(name=file_name, folder=folder_name, project=project.get_id(),
			more_ok=False, zero_ok=False, return_handler=True)
	except:
		logger.debug('%s not found in project %s folder %s' %(file_name, project.get_id(), folder_name))
		try: #maybe it's just  filename in the default workspace
			file_handler = dxpy.DXFile(dxid=identifier, mode='r')
		except:
			logger.debug('%s not found as a dxid' %(identifier))
			file_handler = resolve_accession(identifier, key)

	if not file_handler:
		logger.warning("Failed to resolve file identifier %s" %(identifier))
		return None
	else:
		logger.debug("Resolved file identifier %s to %s" %(identifier, file_handler.name))
		return file_handler


@dxpy.entry_point('main')
def main(reads1, bwa_aln_params, bwa_version, samtools_version, reads2, reference_tar, key, debug):

	if debug:
		logger.setLevel(logging.DEBUG)
	else:
		logger.setLevel(logging.INFO)


	#for each input fastq decide if it's specified as an ENCODE file accession number (ENCFF*)


	reads1_files = [resolve_file(read, key) for read in reads1]
	if len(reads1_files) > 1:
		pool_applet = dxpy.find_one_data_object(
			classname='applet', name='pool', folder=APPLET_FOLDER, project=dxpy.PROJECT_CONTEXT_ID,
			zero_ok=False, more_ok=False, return_handler=True)
		logger.debug('reads1_files:%s' %(reads1_files))
		logger.debug('reads1_files ids:%s' %([dxf.get_id() for dxf in reads1_files]))
		logger.debug('reads1_files dxlinks:%s' %([dxpy.dxlink(dxf) for dxf in reads1_files]))
		pool_subjob = pool_applet.run({"inputs": [dxpy.dxlink(dxf) for dxf in reads1_files]})
		reads1_file = pool_subjob.get_output_ref("pooled")
	else:
		reads1_file = reads1_files[0]
	reads2_file = resolve_file(reads2, key)
	reference_tar_file = resolve_file(reference_tar, key)

	logger.info('Resolved reads1 to %s', reads1_file)
	if reads2:
		logger.info('Resolved reads2 to %s', reads2_file)
	logger.info('Resolved reference_tar to %s', reference_tar_file)

	output = {}
	output.update({'reads1': reads1_file})
	if reads2:
		output.update({"reads2": reads2_file})
	output_json = {
		"reads1": reads1_file,
		"reference_tar": reference_tar_file,
		"bwa_aln_params": bwa_aln_params,
		"bwa_version": bwa_version,
		"samtools_version": samtools_version
	}
	if reads2:
		output_json.update({'reads2': reads2_file})
	output.update({'output_JSON': output_json})
	#logger.info('Exiting with output_JSON: %s' %(json.dumps(output)))
	#return {'output_JSON': json.dumps(output)}

	logger.info('Exiting with output: %s' %(output))
	return output

dxpy.run()
