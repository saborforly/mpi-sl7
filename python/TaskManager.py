
import Queue
import time
import os
import traceback
import threading
from BaseThread import BaseThread
from Task import TaskStatus
from python.Task import ChainTask,Task
import python.HttpServer as HttpServer
from Util import Config
import re

from Util import logger
taskmgr_log = logger.getLogger('AppMgr')

class TaskFromJupyter(BaseThread):
    def __init__(self):
        BaseThread.__init__(self,'TaskFromJupyter')
        self.task_queue = Queue.Queue()
        self.sleep_flag = False
        self.runflag = True
        
        #get Task From httclient
        Config.Config()
        port_file = Config.Config.getCFGattr('rundir')+'/port.txt'
        with open(port_file, 'r') as f:
            port_content = f.read()
            ip = re.findall(".*ifname#(.*)\$.*",port_content)[0]
            port = re.findall(".*port#(.*)\$if.*",port_content)[0]
                

        self.http = HttpServer.HttpThread(ip, int(port)+1)
        
        self.tid= 0
        self.tid_ctl=0
        
    def get_task_queue(self):
        return self.task_queue
    
    def setup_app(self):
        initask = Task(-1)
        initask.boot = 'start'
        taskmgr_log.debug('[TaskMgr] Task: create setup status: %s'%(initask.boot))
        return initask
    def uninstall_app(self):
        fin_task = Task(-1)
        fin_task.boot = 'stop'
        taskmgr_log.debug('[TaskMgr] Task: create setup status: %s'%(fin_task.boot))
        return fin_task
    
    def run(self):
        self.http.setDaemon(True)
        self.http.start()
        while not self.get_stop_flag():
            
            while not self.http.get_jupyterTask_queue().empty():
                jupyterTask_dict = self.http.get_jupyterTask_queue().get()
                print(jupyterTask_dict)
                #jupyterTask_dict={'status':'pause','cut': {'cutQ':1 , 'cutT':2},'evt_filelist':"/"}
                if jupyterTask_dict.has_key('status'):
                    if jupyterTask_dict['status'] == 'start' or jupyterTask_dict['status'] == 'addFile':
                        #split evt_filelist to worker n
                        if jupyterTask_dict.has_key('evt_filelist'):
                            n=1
                            for i in range(n):
                                self.tid+=1
                                task = Task(self.tid)
                                
                                task.boot.append(jupyterTask_dict['status'])
                                task.data = {i:jupyterTask_dict['evt_filelist']}
                                if jupyterTask_dict.has_key('cut'):
                                    task.args = jupyterTask_dict['cut']
                                self.task_queue.put(task)
                        else:
                            continue
                    #status : pause continue stop
                    else :
                        self.tid_ctl-=1
                        task = Task(self.tid_ctl)
                        
                        task.boot.append(jupyterTask_dict['status'])
                        self.task_queue.put(task)
                    #task.initial(self.boot, self.args, self.data, res_dir="./")
                    taskmgr_log.info('[TaskMgr] Get task %s'%task.toDict())        
                    
    
                    
        
