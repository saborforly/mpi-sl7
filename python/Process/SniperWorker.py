import time
import types
import os,sys
import getpass
sys.path.append(os.environ['DistJETPATH'])
import threading
import select
import subprocess
import psutil
import Queue
import traceback
from Parser import Parser
from python.Task import Task
import python.Util.Config as Config

import Sniper

class status:
    (SUCCESS, FAIL, TIMEOUT, OVERFLOW, ANR, UNKOWN) = range(0,6)
    DES = {
        SUCCESS: 'SUCCESS',
        FAIL: 'Task fail, return code is not zero',
        TIMEOUT: 'Run time exceeded',
        OVERFLOW: 'Memory overflow',
        ANR: 'No responding',
        UNKOWN:'Unkown error'
    }
    @staticmethod
    def describe(stat):
        if status.DES.has_key(stat):
            return status.DES[stat]

class CommandPack:
    def __init__(self, task, task_log=None, proc_log=None,finalize_flag=False):
        self.tid = task.tid
        self.status = task.boot
        self.cut = task.args
        self.evt_filelist = task.data

        self.task_log = task_log
        self.proc_log = proc_log
        self.finalize_flag = finalize_flag

#FIXME start a sh process, cannot know when the command finished
#start a thread
class SniperWorker(threading.Thread):
    def __init__(self,logpath, timeout=None,ignoreFail=False, task_callback=None, finalize_callback=None):
        """
        :param initial: the command of setup
        :param timeout: select time out
        :param ignoreFaile:
        :param hook: when complete tasks, call this method
        """
        super(SniperWorker,self).__init__()
        
        self.ignoreFail = ignoreFail
        
        self.exec_queue_lock = threading.RLock()
        self.executable = Queue.Queue()

        self.log = open(logpath,'w+')
        self.hook = task_callback
        self.finalize_callback = finalize_callback

        self.stdout = subprocess.PIPE
        self.stdin = subprocess.PIPE
        self.process = psutil.Popen(['bash'], stdin=self.stdin, stdout=self.stdout, stderr=subprocess.STDOUT,preexec_fn=os.setsid)
        self.pid = self.process.pid        

        self.log.write('@sniper: start sniper for tasks, pid=%d\n'%self.pid)
        self.log.flush()

        self.timeout = timeout
        self.recode = None
        self.status = None

        self.start_time = None
        self.end = None
        self.killed = None
        self.fatalLine = None
        self.logParser = Parser()

        self.stop_flag = False
        
        self.tag_dict={}
        
        self.exit = False
        self.TaskLogDir = Config.Config.getCFGattr('rundir')+'/task_log'
        
        self.cutQ = None
        self.cutT = None
        self.taskFile = None
        self.sniper_state_queue = Queue.Queue()
        self.untag_first_window = []
        self.run_flag = True 
        #print 'task dir= %s'%self.TaskLogDir
        if not os.path.exists(self.TaskLogDir):
            try:
                os.mkdir(self.TaskLogDir)
            except:
                pass
            
    def stop(self,force=False):
        #print "someone call stop\n"
        self.stop_flag = True
        self.process.wait()
    def set_task(self,task, genLog=True):
        
        task_log=self.TaskLogDir+'/task_'+str(task.tid)+'.tmp'

        if genLog:
            #print "res_dir=%s, tid=%s"%(task.res_dir,str(task.tid))
            commpack = CommandPack(task, task_log=task_log)
        else:
            commpack = CommandPack(task, proc_log=self.log, finalize_flag=True)
        self.executable.put(commpack)
        self.log.write('[Proc] Add task command=%s, logfile=%s\n'%(commpack.status, str(commpack.task_log)+'|'+str(commpack.proc_log)))
        self.log.flush()
        
    def finalize_and_cleanup(self, task):
        self.exit = True
        self.set_task(task,genLog=False) 
    def run(self):
        status_list = []
        while not self.stop_flag:
            try:
                self.exec_queue_lock.acquire()
                if not self.executable.empty():
                    commpack = self.executable.get()
                    self.exec_queue_lock.release()
                    # for one task ,multi script
                    # get script list from commpack
                    status_list = commpack.status
                    logfile = None
                    if commpack.task_log:
                        logfile = open(commpack.task_log, 'w+')
                    elif commpack.proc_log:
                        logfile = commpack.proc_log
                    if commpack.finalize_flag:
                        self.hook = self.finalize_callback
                    sc_len = len(status_list)
                    index = 0
                    while len(status_list) != 0 and len(status_list) > index:
                        script = status_list[index]
                        index+=1
                        
                        if self.exit==True:
                            print ("<process> exiting...")
                            logfile.write("[Proc] Ready to exit\n")
                            logfile.flush()
                            self.stop_flag=True
                            break
                        
                        #Run task SniperPython
                        evt_filelist = commpack.evt_filelist
                        cut = commpack.cut
                        if cut.has_key("cutQ"):
                            self.set_cutQ(cut["cutQ"])
                        if cut.has_key("cutT"):
                            self.set_cutT(cut["cutT"])
                        for k,v in evt_filelist.items():
                            self.set_file_list(v)


                        self.start_time = time.time()
                        self.start_sniper()    
                        self.end = time.time()
                        self.status = status.SUCCESS

                        if len(self.untag_first_window)>0:
                            self.tag_dict[script]=self.untag_first_window
                        else:
                            self.tag_dict[script]="None"
                            
                        self.recode=0
                        logfile.write("\ncut Q = %f \ncut T = %f\n evt file list = %s\n\n" % (self.task_cutQ,self.task_cutT,self.task_file_list))
                        #logfile.write("\n script file = %s \n tag = %s\n\n" % (script, self.tag_dict[script]))
                        logfile.write("\nstart time = %s \nend time = %s\n\n" % (time.asctime(time.localtime(self.start_time)), time.asctime(time.localtime(self.end))))
                        logfile.flush()
                        #1 task do once hook
                    if self.hook and callable(self.hook):
                        self.hook(self.status, self.recode, self.start_time, self.end, os.path.abspath(logfile.name))

                    if commpack.task_log:
                        logfile.flush()
                        logfile.close()

                else:
                    self.exec_queue_lock.release()
                    time.sleep(0.1)
            except Exception,e:
                self.log.write('@Process catch error: %s\n'%e.message)
                print traceback.format_exc()

    def set_cutQ(self,cut_q):
        self.task_cutQ = cut_q
    def set_cutT(self,cut_t):
        self.task_cutT = cut_t
        
    def set_file_list(self,file):
        self.task_file_list = file
        
    def get_untag(self):
        return self.untag_first_window
    def put_sniper_state(self, state):
        #pause 0 ; running 1 ; stop 2; 
        self.sniper_state_queue.put(state)
    def get_sniper_state(self):
        if not self.sniper_state_queue.empty():
            return self.sniper_state_queue.get()
        else:
            return None
    #input cut val and Event file
    #output untag correlation event in first window  
    def start_sniper(self):
        #self.task_cutQ, self.task_cutT, self.task_file_list
        import ForMpi 
        task = ForMpi.MpiTask("task")
        task.setEvtMax(10)
        task.setLogLevel(2)
    
        import EvtConfig
    
        EvtConf = task.createSvc("EvtConfigSvc")
        EvtConf.property("seqListFile").set("/junofs/users/liuyan/OEC/EventFilter/seq.xml")
        EvtConf.property("sigListFile").set("/junofs/users/liuyan/OEC/EventFilter/sig.xml")    
    
        import EvtStore
        task.property("svcs").append("EvtStoreSvc")

        import EvtResult
        task.property("svcs").append("EvtResultSvc")


        import EvtSteering
        import EvtAlgorithms

        task.property("algs").append("StepHandler")
        time.sleep(20)

        task.show()
        task.run()
        #self.sniper_state_queue.queue.clear()
        while task.getRunFlag():
            state = self.get_sniper_state()
            if state is None:
                continue
            task.setTaskState(state)
        task.setTaskState(-1)
        task.freeThread() 
       
        #evt_tag=forMpi.getMpiTag()
        #self.untag_first_window = forMpi.getMpiTag()
        
       
if __name__ == '__main__':
    comm = ['$JUNOTESTROOT/python/JunoTest/junotest UnitTest Tutorial\n','$JUNOTESTROOT/python/JunoTest/junotest UnitTest JunoTest\n','$JUNOTESTROOT/python/JunoTest/junotest UnitTest Cf252\n','#exit#']
    setup = 'source /afs/ihep.ac.cn/soft/juno/JUNO-ALL-SLC6/Pre-Release/J17v1r1-Pre2/setup.sh'
    import logging
    log = logging.getLogger('test.log')
    with open('output.txt','w+') as output:
        proc = SniperWorker(setup,output,log,hook=hook)
        print "@proc setup recode=%d"%proc.initialize()
        thread = threading.Thread(target=add,args=[proc,comm])
        thread.start()
        #proc.set_exe(comm)
        print "proc.start = %s, thread.start=%s"%(proc.start,thread.start)
        proc.start()
        proc.join()

    print '@proc finished'

