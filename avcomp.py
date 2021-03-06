#!/usr/bin/env python3

""" Virustotal AV Comparator

    Required libraries:
        - requests (can be installed manually or through pip)
        - PTable (can be installed manually or through pip)
"""

__author__ = "httpe, Xiaokui Shu"
__copyright__ = "Copyright 2016-2017, The VirusTotal AV Comparator Project"
__license__ = "Apache"
__version__ = "1.9"
__maintainer__ = "httpe"
__status__ = "Prototype"
__date__ = "2017-05-31"
__contact__ = "https://github.com/httpe/Virustotal-AV-Comparator"


import sys
import os
import hashlib
import argparse
import logging
import json
import time
import csv
import stat


import requests
from prettytable import PrettyTable


from requests.adapters import HTTPAdapter
#from requests.packages.urllib3.poolmanager import PoolManager
from urllib3.poolmanager import PoolManager
import ssl

class MyAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       ssl_version=ssl.PROTOCOL_TLSv1)
        

def has_hidden_attribute(filepath):
    """
    Check if a file is hidden (Windows)

    @param filepath: path to the file

    """
    
    return bool(os.stat(filepath).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)

def cur_file_dir():
    """
    Obtain the path to the containing folder of this script

    If the program is plain script, return the script folder;
    If the program is compiled into exe, return the exe folder

    """
    path = sys.path[0]
    if os.path.isdir(path):
        return path
    elif os.path.isfile(path):
        return os.path.dirname(path)


def sha256sum(filename):
    """
    Efficient sha256 checksum realization

    Take in 8192 bytes each time
    The block size of sha256 is 512 bytes
    """
    with open(filename, 'rb') as f:
        m = hashlib.sha256()
        while True:
            data = f.read(8192)
            if not data:
                break
            m.update(data)
        return m.hexdigest()


class VirusTotal(object):
    def __init__(self):
        self.apikey = ""
        self.URL_BASE = "https://www.virustotal.com/vtapi/v2/"
        self.HTTP_OK = 200
        self.ATTEMPT = 3

        self.headers = {
          "Accept-Encoding": "gzip, deflate",
          "User-Agent" : "gzip,  My Python requests library example client or username"
          }

        # whether the API_KEY is a public API. limited to 4 per min if so.
        self.is_public_api = True
        # if needed (public API), sleep this amount of time between requests
        self.PUBLIC_API_SLEEP_TIME = 15
        self.last_request_time = time.perf_counter()

        self.logger = logging.getLogger("virt-log")
        self.logger.setLevel(logging.INFO)
        self.scrlog = logging.StreamHandler()
        self.scrlog.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        self.logger.addHandler(self.scrlog)
        self.is_verboselog = False

        self.is_recursive = False
        self.ignore_hidden = True

        self.reanalyze_time = ''
        self.statpath = 'Result.csv'

        self.vt_session = requests.Session()
        self.vt_session.mount(self.URL_BASE, MyAdapter())

    def list_all_files(self, paths):
        """
        List all file paths

        @param paths: a list of paths, return all the files indicated by or situated in those paths

        No recursive search, and subdirectories not listed if self.is_recursive=False (default)
        
        """
        filenames = []

        for path in paths:
            assert os.path.isfile(path) or os.path.isdir(path), "File Not Found: {}".format(path)

            if os.path.isfile(path):
                filenames.append(path)
            else:
                if self.is_recursive:
                    
                    for root, folders, files in os.walk(path):
                        for file_name in files:
                            file_path = os.path.join(root, file_name)
                            if self.ignore_hidden and has_hidden_attribute(file_path):
                                continue

                            if os.path.exists(file_path):
                                filenames.append(file_path)
                                

                else:
                    filenames += filter(lambda x: not (self.ignore_hidden and has_hidden_attribute(x)),
                                  filter(os.path.isfile, map(lambda x: os.path.join(os.path.abspath(path), x), os.listdir(path))))
    
        return filenames
        
    def send_files(self, paths):
        """
        Send files to scan

        Return: [Bool] list of send result
        
        @param paths: list of target files/folders
        """
              
        filenames = self.list_all_files(paths)

        result = []

        for filename in filenames:

            file_size = os.path.getsize(filename) 
            if  file_size >= 32000000:
                self.logger.warning("%s: \n\t  File too large (size: %.2f MB >= 32MB), upload failed",
                                    filename, file_size/1000000)
                result.append(False)
                
            else:
                
                res = self.upload(filename)
                
                if res == None:
                    self.logger.warning("%s: \n\t  Send file failed", filename)
                    result.append(False)
                        
                elif res.status_code != self.HTTP_OK:
                    self.logger.warning("%s: \n\t  Send file failed, HTTP: %d", filename, res.status_code)
                    result.append(False)
                
                else:
                    resmap = json.loads(res.text)
                    if not self.is_verboselog:
                            self.logger.info("%s: \n\t  Send file success, HTTP: %d", filename, res.status_code)
                    else:
                            self.logger.info("%s: \n\t  Send file success: %s, HTTP: %d, content: %s", filename, res.status_code, res.text)

                    result.append(True)
                    


        return result
    
    def compare_av(self, paths):
        """
        Comapre the performance of all Anti-Virus products

        @param paths: list of target files/folders
        """

        filenames = self.list_all_files(paths)
        
        avs = {}
        filename_list = []
        av_count = {}
        effective_file_counter = 0
        
        for filename in filenames:
            sha256chksum = sha256sum(filename)
            filename_list.append(os.path.basename(filename))

            res = self.retrieve_report(sha256chksum)

            if res == None:
                self.logger.warning("%s: \n\t  Retrieve report failed", filename)
                for av in avs:
                    avs[av].append('Failed')       
            
            elif res.status_code != self.HTTP_OK:
                self.logger.warning("%s: \n\t  Retrieve report failed, HTTP: %d", filename, res.status_code)
                for av in avs:
                    avs[av].append('Failed')       
                            
            else:
                resmap = json.loads(res.text)             

                if resmap['response_code'] == 0:

                    self.logger.warning("%s: \n\t  File not found, now uploading...", filename)


                    upload_res = self.send_files([filename])

                    if upload_res[0]:
                        for av in avs:
                            avs[av].append('Scanning')
                    else:
                        for av in avs:
                            avs[av].append('Failed')

                else:

                    if resmap["scan_date"] < self.reanalyze_time:

                        self.logger.warning("%s: \n\t  Report too old %s, reanalyzing...",
                                                                filename, resmap["scan_date"])
                         
                        res = self.regenerate_report(sha256chksum)
                        
                        if res == None:
                            self.logger.warning("%s: \n\t  Regenerate report failed", \
                                                                            filename, res.status_code)
                            for av in avs:
                                avs[av].append('Failed') 
                        
                        elif res.status_code != self.HTTP_OK:
                            self.logger.warning("%s: \n\t  Regenerate report failed, HTTP: %d", \
                                                                            filename, res.status_code)
                            for av in avs:
                                avs[av].append('Failed')      
                                        
                        else:
                            self.logger.info("%s: \n\t  Reanalyze request success", filename)
                            for av in avs:
                                avs[av].append('Reanalyzing')

                                                
                                
                    else:
                                    
                        effective_file_counter += 1
                        self.logger.info("%s: \n\t  Scandate: %s, Positive/Total: %d/%d",
                                                         filename,
                                                         resmap["scan_date"],
                                                         resmap["positives"],
                                                         resmap["total"])

                        filename_list[-1] += '\n' + resmap["scan_date"]

                        for av in avs:
                                if av in resmap["scans"]:
                                    avres = resmap["scans"][av]
                                    if avres["detected"]:
                                        avs[av].append(avres["result"])
                                        av_count[av] = (av_count[av][0]+1,av_count[av][1]+1)
                                    else:
                                        avs[av].append("Clean")
                                        av_count[av] = (av_count[av][0],av_count[av][1]+1)
                                else:
                                    avs[av].append("Unknown")
                                        
                        for av in resmap["scans"]:
                            if av not in avs:
                                avres = resmap['scans'][av]
                                avs[av] = ['Unknown']*(len(filename_list)-1)
                                if avres["detected"]:
                                    avs[av].append(avres["result"])
                                    av_count[av] = (1,1)
                                else:
                                    avs[av].append("Clean")
                                    av_count[av] = (0,1)
                
          


        with open(os.path.join(cur_file_dir(),self.statpath),'w', newline='') as f:
            writer = csv.writer(f)
            
        
            pt = PrettyTable(["Rank", "Anti Virus", "Killed/Scanned/Eff", "Effective Killing Rate"])
            writer.writerow(["Rank", "Anti Virus", "Killed/Scanned/Eff", "Effective Killing Rate"])

            pt.align["Anti Virus"] = "l"
            
            kill_rate = []
            for av in av_count:
                #kill_rate.append((av, av_count[av][0]/av_count[av][1]))
                kill_rate.append((av, av_count[av][0]/effective_file_counter))
            kill_rate = sorted(kill_rate, key=lambda t: t[1], reverse=True)
            
            rank = 0
            counter = 0
            last_rate = -1
            for av,rate in kill_rate:
                counter = counter + 1
                if rate != last_rate:
                    rank = counter
                    last_rate = rate
                pt.add_row([rank, av, "{}/{}/{}".format(
                    av_count[av][0], av_count[av][1], effective_file_counter), "{0:.2%}".format(rate)])
                
                writer.writerow([rank, av, "'{}/{}/{}'".format(
                    av_count[av][0], av_count[av][1], effective_file_counter), "{0:.2%}".format(rate)])

            self.logger.info("Effective Killing rate is calculated on files scanned by by at least one AV")
            self.logger.info("Effective files: %d, Total files: %d", effective_file_counter, len(filename_list))
            print(pt)

            writer.writerow([])
            writer.writerow([])

            writer.writerow(["Effective Killing rate is calculated on files scanned by by at least one AV"])
            writer.writerow(["Effective files: {}, Total files: {}".format(effective_file_counter, len(filename_list))])

            
            #pt2 = PrettyTable(["Anti Virus"] + filename_list)
            writer.writerow(["Anti Virus"] + filename_list)
            
            pt.align["Anti Virus"] = "l"
            for av,rate in kill_rate:
                #pt2.add_row([av] + avs[av])
                writer.writerow([av] + avs[av])
            #print(pt2)

        
    def retrieve_files_reports(self, paths):
        """
        Retrieve Report for file

        @param paths: list of target files/folders
        """

        filenames = self.list_all_files(paths)

        resmapdict = {}
        
        for filename in filenames:
            resmapdict[filename] = None

            res = self.retrieve_report(sha256sum(filename))

            if res == None:
                self.logger.warning("%s: \n\t  Retrieve report failed: HTTP: %d", filename, res.status_code)
                
            elif res.status_code != self.HTTP_OK:
                self.logger.warning("%s: \n\t  Retrieve report failed: HTTP: %d", filename, res.status_code)

            else:
                resmap = json.loads(res.text)
                resmapdict[filename] = resmap

                if resmap['response_code'] == 0:
                    self.logger.warning("%s: \n\t  File not found", filename)
                else:             
                    self.logger.info("%s: \n\t  Scandate: %s, Positive/Total: %d/%d",
                                     filename,
                                     resmap["scan_date"],
                                     resmap["positives"],
                                     resmap["total"])


        return resmapdict
        
            

    def retrieve_from_chksum(self, paths):
        """
        Retrieve Report form checksums in the metafile

        @param paths: list of metafiles, in which each line is a checksum, best use sha256
        """

        filenames = self.list_all_files(paths)


        for filename in filenames:
            try:
                with open(filename) as f:
                    for line in f:
                        checksum = line.strip()
                        res = self.retrieve_report(checksum)
                        
                        if res == None:
                            self.logger.warning("%s: \n\t  Retrieve report failed", checksum)
                                
                        elif res.status_code != self.HTTP_OK:
                            self.logger.warning("%s: \n\t  Retrieve report failed, HTTP: %d", checksum, res.status_code)

                        else:
                            resmap = json.loads(res.text)

                            if resmap['response_code'] == 0:
                                self.logger.warning("%s: \n\t  Checksum not found", checksum)
                            else:
                                if not self.is_verboselog:
                                    self.logger.info("%s: \n\t  Retrieve report success, HTTP: %d, scan_date: %s, positives/total: %d/%d",
                                                    checksum, res.status_code, resmap["scan_date"], resmap["positives"], resmap["total"])
                                else:
                                    self.logger.info("%s: \n\t  Retrieve report success, HTTP: %d, content: %s", checksum, res.status_code, res.text)
                            
            except IOError as e:
                print(e.args)

    def retrieve_report(self, chksum):
        """
        Retrieve Report for the file checksum

        4 retrieval per min if only public API used

        @param chksum: sha256sum of the target file
        """

        time_since_last_request = time.perf_counter() - self.last_request_time
        
        if self.is_public_api \
            and time_since_last_request <= self.PUBLIC_API_SLEEP_TIME:
            
            time.sleep(self.PUBLIC_API_SLEEP_TIME - time_since_last_request)

            
        url = self.URL_BASE + "file/report"
        params = {"apikey": self.apikey, "resource": chksum}

        res = None
        
        for attempt in range(self.ATTEMPT):
            try:
                #res = requests.post(url, data=params)
                res = self.vt_session.get(url, params=params, headers=self.headers)
                
            except SSLError as e:
                self.vt_session = requests.Session()
                self.vt_session.mount(self.URL_BASE, MyAdapter())
                continue
                
            finally:
                self.last_request_time = time.perf_counter()
                
            if res.status_code != self.HTTP_OK:
                continue
            else:
                break
            

        return res
    
    def regenerate_report(self, chksum):
        """
        Regenerate Report for the uploaded file checksum

        4 retrieval per min if only public API used

        @param chksum: sha256sum of the target file
        """
        time_since_last_request = time.perf_counter() - self.last_request_time
        
        if self.is_public_api \
            and time_since_last_request <= self.PUBLIC_API_SLEEP_TIME:
            
            time.sleep(self.PUBLIC_API_SLEEP_TIME - time_since_last_request)

        url = self.URL_BASE + "file/rescan"
        params = {"apikey": self.apikey, "resource": chksum}
        
        res = None
        
        for attempt in range(self.ATTEMPT):
            try:
                #res = requests.post(url, data=params)
                res = self.vt_session.post(url, params=params, headers=self.headers)
                
            except SSLError as e:
                self.vt_session = requests.Session()
                self.vt_session.mount(self.URL_BASE, MyAdapter())
                continue
                
            finally:
                self.last_request_time = time.perf_counter()
                
            if res.status_code != self.HTTP_OK:
                continue
            else:
                break
        
        
        
        return res
            

    def upload(self, path):

        time_since_last_request = time.perf_counter() - self.last_request_time
        
        if self.is_public_api \
            and time_since_last_request <= self.PUBLIC_API_SLEEP_TIME:
            
            time.sleep(self.PUBLIC_API_SLEEP_TIME - time_since_last_request)

        url = self.URL_BASE + "file/scan"
        params = {"apikey": self.apikey}

        filename = os.path.basename(path)
        
        res = None

        for attempt in range(self.ATTEMPT):
            try:
                with open(path, 'rb') as file:
                    #res = requests.post(url, data=params, files={"file": file})
                    res = self.vt_session.post(url, params=params, files={"file": (filename, file)})
                    
            except IOError as e:
                print(e.args)
                
            except SSLError as e:
                self.vt_session = requests.Session()
                self.vt_session.mount(self.URL_BASE, MyAdapter())
                continue
                
            finally:
                self.last_request_time = time.perf_counter()
                
            if res.status_code != self.HTTP_OK:
                continue
            else:
                break

        return res


if __name__ == "__main__":


    name_version = 'Virustotal AV Comparator ' + __version__;

    vt = VirusTotal()
    try:
        with open(os.path.join(cur_file_dir(), 'apikey.txt')) as keyfile:
            vt.apikey = keyfile.read().strip()
    except:
        print(name_version)
        print('[Error] Please put your VirusTotal API Key in file "apikey.txt" under the current directory')
        print('[Error] For more information about API Key, please refer to "https://www.virustotal.com/en/documentation/public-api/"')
        input("Press the enter key to exit.")
        sys.exit()

    

    parser = argparse.ArgumentParser(description = name_version)

    parser.add_argument('paths', metavar='PATH', nargs='*',
                            help='File/Folder to be scanned', default=[])

    parser.add_argument("-c", "--compare", help="cross-compare all anti-virus products (default action)", action="store_true")
    parser.add_argument("-s", "--send", help="send a file or a directory of files to scan", action="store_true")
    parser.add_argument("-r", "--retrieve", help="retrieve reports on a file or a directory of files", action="store_true")
    parser.add_argument("-C", "--checksum_file", help="retrieve reports based on checksums in a metafile (one sha256 checksum for each line)", action="store_true")
    
    parser.add_argument("-p", "--private", help="signal the API key belongs to a private API service", action="store_true")
    parser.add_argument("-v", "--verbose", help="print verbose log (everything in response)", action="store_true")
    parser.add_argument("-R", "--recursive", help="traverse the path recursively", action="store_true")
    parser.add_argument("-H", "--hidden", help="do not ignore hidden files", action="store_true")


    parser.add_argument("-S", "--statistic", help="write result statistic in a CSV file (default: Result.csv)", metavar="STATPATH")
    parser.add_argument("-l", "--log", help="log actions and responses in file (default: log.txt)", metavar="LOGFILE")
    parser.add_argument("-t", "--time", help="reanalyze the file if the report was generated before the time, format 'YYYY-MM-DD hh:mm:ss'/'now'", metavar="TIME")

    args = parser.parse_args()


    logpath = os.path.join(cur_file_dir(), 'log.txt')
    if args.log:
        logpath = args.log
        
    filelog = logging.FileHandler(logpath)
    filelog.setFormatter(logging.Formatter("[%(asctime)s %(levelname)s] %(message)s", datefmt="%m/%d/%Y %I:%M:%S"))
    vt.logger.addHandler(filelog)

    if args.time:
        if args.time == 'now':
            vt.reanalyze_time = '2099-12-31 00:00:00'
        else:
            vt.reanalyze_time = args.time

    if args.private:
        vt.is_public_api = False

    if args.verbose:
        vt.is_verboselog = True

    if args.recursive:
        vt.is_recursive = True

    if args.hidden:
        vt.ignore_hidden = False

    if args.statistic:
        vt.statpath = args.statistic

    

    #print(type(args.paths))
    #print(args.paths)
    #input("aaa")
    if args.paths == []:
        print("[ERROR] Please specify/drag&drop a file/folder to be scanned")
        parser.print_help()
        input("Press the enter key to exit.")
        
    else:

        # system init end, start to perform operations
        api_comments = {True: 'Public', False: 'Private'}
        vt.logger.info("API KEY loaded. %s API used: %s", api_comments[vt.is_public_api], vt.apikey)
        
        
        if args.compare:
            vt.compare_av(args.paths)
        elif args.send:
            vt.send_files(args.paths)
        elif args.retrieve:
            vt.retrieve_files_reports(args.paths)
        elif args.checksum_file:
            vt.retrieve_from_chksum(args.paths)
        else:
            vt.compare_av(args.paths)
            
        input("Action finished, press the enter key to exit.")
    
