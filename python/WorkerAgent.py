import Queue
import os,sys
import subprocess
import threading
import time
import traceback
import types
#import psutil

import IR_Buffer_Module as IM
from Util import HealthDetect as HD
from BaseThread import BaseThread
from MPI_Wrapper import Tags ,Client, MSG
from Util import logger
from WorkerRegistry import WorkerStatus
from Util import Config
from Util import Package
from Task import Task
from Process.SniperWorker import SniperWorker
from Process.Process import status as ProcessStatus
import python.Util.Read_Data as rdata
import python.Util.Recoder as Recoder

wlog = None

# class status:
#     (SUCCESS, FAIL, TIMEOUT, OVERFLOW, ANR) = range(0,5)
#     DES = {
#         FAIL: 'Task fail, return code is not zero',
#         TIMEOUT: 'Run time exceeded',
#         OVERFLOW: 'Memory overflow',
#         ANR: 'No responding'
#     }
#     @staticmethod
#     def describe(stat):
#         if status.DES.has_key(stat):
#             return status.DES[stat]


class HeartbeatThread(BaseThread):
    """
    ping to master, provide information and requirement
    """
    def __init__(self, client, worker_agent, cond):
        BaseThread.__init__(self, name='HeartbeatThread')
        self._client = client
        self.worker_agent = worker_agent
        self.queue_lock = threading.RLock()
        self.acquire_queue = Queue.Queue()         # entry = key:val
        self.interval = Config.Config.getCFGattr('HeartBeatInterval') if Config.Config.getCFGattr('HeartBeatInterval') else 0.1
        self.cond = cond
        global wlog
    def run(self):
        task_acquire=0 # timer for acquire tasks from master when is halted
        #add first time to ping master, register to master
        send_dict = {}
        send_dict['flag'] = 'FP'
        send_dict[Tags.MPI_REGISTY] = {'capacity':self.worker_agent.capacity}
        send_dict['ctime'] = time.time()
        wlog.debug('[HeartBeat] time stamp = %f'%send_dict['ctime'])
        send_dict['uuid'] = self.worker_agent.uuid
        send_str = Package.pack_obj(send_dict)
        send_str = Package.pack2json({'uuid':self.worker_agent.uuid,'dict':send_str})
        wlog.debug('[HeartBeat] Send msg = %s'%send_dict)
        #-----test----
        #ret = 0
        #print("MPI_REGISTY: send_dict=%s"%(send_dict))
        #----test----
        ret = self._client.send_string(send_str, len(send_str),0,Tags.MPI_REGISTY)
        if ret != 0:
            #TODO send error,add handler
            pass

        # wait for the wid and init msg from master
        self.cond.acquire()
        self.cond.wait()
        self.cond.release()

        while not self.get_stop_flag():
            try:
                self.queue_lock.acquire()
                send_dict.clear()
                while not self.acquire_queue.empty():
                    tmp_d = self.acquire_queue.get()
                    if send_dict.has_key(tmp_d.keys()[0]):
                        wlog.warning('[HeartBeatThread]: Reduplicated key=%s when build up heart beat message, skip it'%tmp_d.keys()[0])
                        continue
                    send_dict = dict(send_dict, **tmp_d)
                self.queue_lock.release()
                send_dict['Task'] = []
                while not self.worker_agent.task_completed_queue.empty():
                    task = self.worker_agent.task_completed_queue.get()
                    send_dict['Task'].append(task)
                send_dict['uuid'] = self.worker_agent.uuid
                send_dict['wid'] = self.worker_agent.wid
                st = self.worker_agent.get_status()
                if st:
                    self.worker_agent.status = st
                send_dict['wstatus'] = self.worker_agent.status
                if send_dict['wstatus'] == WorkerStatus.IDLE and self.worker_agent.halt_flag:
                    if task_acquire == 10:
                        wlog.debug('[HeartBeat] Send Task add msg')
                        send_dict[Tags.TASK_ADD] = 1
                        task_acquire=0
                    else:
                        task_acquire+=1
                send_dict['health'] = self.worker_agent.health_info()
                send_dict['rTask'] = self.worker_agent.getRuntasklist()
                send_dict['ctime'] = time.time()
                send_str = Package.pack_obj(send_dict)
                send_str = Package.pack2json({'uuid':self.worker_agent.uuid,'dict':send_str})
                #wlog.debug('[HeartBeat] Send msg = %s'%send_dict)
                ret = self._client.send_string(send_str, len(send_str), 0, Tags.MPI_PING)
                # -----test----
                #ret = 0
                #print("MPI_PING: send_dict=%s" % ( send_dict))
                # ----test----
                if ret != 0:
                    #TODO add send error handler
                    pass
            except Exception:
                wlog.error('[HeartBeatThread]: unkown error, thread stop. msg=%s', traceback.format_exc())
                break
            else:
                time.sleep(self.interval)

        # the last time to ping Master
        if not self.acquire_queue.empty():
            remain_command = ''
            while not self.acquire_queue.empty():
                remain_command+=self.acquire_queue.get().keys()
            wlog.waring('[HeartBeat] Acquire Queue has more command, %s, ignore them'%remain_command)
        send_dict.clear()
        send_dict['wid'] = self.worker_agent.wid
        send_dict['uuid'] = self.worker_agent.uuid
        send_dict['flag'] = 'LP'
        send_dict['Task'] = {}
        while not self.worker_agent.task_completed_queue.empty():
            task = self.worker_agent.task_completed_queue.get()
            #FIXME: change to task obj
            send_dict['Task'] = dict(send_dict['Task'],**task)
        # add node health information
        send_dict['health'] = self.worker_agent.health_info()
        send_dict['ctime'] = time.time()
        #send_dict['wstatus'] = self.worker_agent.worker.status
        send_str = Package.pack_obj(send_dict)
        send_str = Package.pack2json({'uuid':self.worker_agent.uuid,'dict':send_str})
        wlog.debug('[HeartBeat] Send msg = %s'%send_dict)
        ret = self._client.send_string(send_str, len(send_str), 0, Tags.MPI_PING)
        #-----test----
        #ret = 0
        #print("MPI_PING:  send_dict=%s"%(send_dict))
        #----test----
        if ret != 0:
            #TODO add send error handler
            pass



    def set_ping_duration(self, interval):
        self.interval = interval


class WorkerAgent:

    def __init__(self,name=None,capacity=1):
        import uuid as uuid_mod
        self.uuid = str(uuid_mod.uuid4())
        if name is None:
            name = self.uuid
        #print "my name = %s"%self.uuid
        global wlog
        wlog = logger.getLogger('Worker_%s'%name)
        self.worker_class = None

        self.recv_buff = IM.IRecv_buffer()
        self.__should_stop = False
        Config.Config()
        self.cfg = Config.Config
        import socket
        wlog.info('[Agent] Running on host: %s'%socket.gethostname())
        wlog.debug('[Agent] Start to connect to service <%s>' % self.cfg.getCFGattr('svc_name'))

        self.client = Client(self.recv_buff, self.cfg.getCFGattr('svc_name'), self.uuid)
        self.client.set_portfile(Config.Config.getCFGattr('rundir')+'/port.txt')
        ret = self.client.initial()
        #----test----
        #self.client=None
        #ret = 0
        #----test----
        if ret != 0:
            #client initial error, add handler
            self.client.stop(True)
            wlog.error('[Agent] Client initialize error, errcode = %d'%ret)
            exit()
        if self.cfg.getCFGattr('delay_rec') == 'True':
            self.recoder = Recoder.BaseRecoder(Config.Config.getCFGattr('rundir')+'/Agent-'+self.uuid)

        self.wid = None
        self.appid = None
        self.capacity = capacity
        self.task_queue = Queue.Queue(maxsize=self.capacity+1) #store task obj
        self.removed_tasks=[]
        self.task_completed_queue = Queue.Queue()# store task obj
        self.ignoreTask=[]

        self.initExecutor=None #init task obj
        self.tmpLock = threading.RLock()
        self.finExecutor=None

        self.fin_flag = False
        self.initial_flag = False
        self.app_fin_flag = False
        self.halt_flag = False
        self.task_acquire = False
        self.heartcond = threading.Condition()
        self.heartbeat = HeartbeatThread(self.client, self, self.heartcond)

        self.list_lock=threading.RLock()
        self.worker_list = {}
        self.worker_status={}
        self.cond_list = {}
        self.status = WorkerStatus.NEW
        self.loop_time = 0.1

        #code for read_data
        self.mult_file_path=[]
        self.res_data=None
        self.read_flag=False

    def run(self):
        try:
            wlog.info('[Agent] WorkerAgent run...')
            self.heartbeat.start()
            wlog.info('[WorkerAgent] HeartBeat thread start...')
            while not self.__should_stop:
                time.sleep(self.loop_time) #TODO temporary config for loop interval
                if not self.recv_buff.empty():
                    msg = self.recv_buff.get()
                    if msg.tag == -1:
                        continue
                    message = msg.sbuf[0:msg.size]
                    try:
                        tmp_obj = Package.unpack_from_json(message)['dict']
                        #wlog.debug('tmp_obj=%s'%tmp_obj)
                        recv_dict = Package.unpack_obj(tmp_obj)
                    except:
                        wlog.error('[WorkerAgent] Error occurs when parse msg, <%s>'%traceback.format_exc())
                    for k,v in recv_dict.items():
                        # registery info v={wid:val,init:[TaskObj], appid:v, wmp:worker_module_path}
                        if int(k) == Tags.MPI_REGISTY_ACK:
                            if v.has_key('flag') and v['flag'] == 'NEWAPP':
                                wlog.info('[WorkerAgent] Receive New App msg = %s' % v)
                                v['wid'] = self.wid
                                self.appid = v['appid']
                                self.task_queue.queue.clear()
                                self.task_completed_queue.queue.clear()
                                self.ignoreTask = []
                                self.tmpLock.acquire()
                                try:
                                    self.initExecutor = None
                                    self.finExecutor = None
                                finally:
                                    self.tmpLock.release()
                                self.fin_flag = False
                                self.app_fin_flag = False
                                self.halt_flag = False
                                self.task_acquire = False
                            else:
                                wlog.info('[WorkerAgent] Receive Registry_ACK msg = %s' % v)
                            '''
                            worker_path = v['wmp']
                            if worker_path is not None and worker_path!='None':
                                module_path = os.path.abspath(worker_path)
                                sys.path.append(os.path.dirname(module_path))
                                worker_name = os.path.basename(module_path)
                                if worker_name.endswith('.py'):
                                    worker_name = worker_name[:-3]
                                try:
                                    worker_module = __import__(worker_name)
                                    if worker_module.__dict__.has_key(worker_name) and callable(
                                        worker_module.__dict__[worker_name]):
                                        self.worker_class = worker_module.__dict__[worker_name]
                                        wlog.info('[Agent] Load specific worker class = %s' % self.worker_class)
                                except Exception:
                                    wlog.error('[Agent] Error when import worker module %s, path = %s,errmsg=%s' % (
                                        worker_name, worker_path, traceback.format_exc()))
                            else:
                                wlog.warning('[Agent] No specific worker input, use default')
                            '''
                            try:
                                self.wid = v['wid']
                                self.appid = v['appid']
                                self.tmpLock.acquire()
                                self.iniExecutor = v['init'] # pack init command into one task obj
                                wlog.info('[Agent] init_task:%s, boot=%s'%(self.iniExecutor,self.iniExecutor.boot))
                                self.tmpLock.release()

                                # notify worker initialize
                                wlog.info('[Agent] Start up worker and initialize')
                                self.list_lock.acquire()
                                for i in range(self.capacity):
                                    self.cond_list[i]=threading.Condition()
                                    self.worker_list[i]=Worker(i, self, self.cond_list[i],self.cfg, worker_class=self.worker_class)
                                    self.worker_status[i] = WorkerStatus.NEW
                                    wlog.info('[Agent] Worker %s start' % i)
                                    self.worker_list[i].start()
                                self.list_lock.release()

                                # notify the heartbeat thread
                                wlog.debug('[WorkerAgent] Wake up the heartbeat thread')
                                self.heartcond.acquire()
                                self.heartcond.notify()
                                self.heartcond.release()
                            except Exception:
                                wlog.error("%s"%traceback.format_exc())
                        # add tasks  v=[Task obj]
                        elif int(k) == Tags.TASK_ADD:
                            tasklist = v
                            self.halt_flag = False
                            wlog.info('[WorkerAgent] Add new task : %s' % ([task.tid for task in tasklist]))
                            for task in tasklist:
                                self.task_queue.put(task)
                            count = len(tasklist)
                            self.list_lock.acquire()
                            for worker_id, st in self.worker_status.items():
                                if st == WorkerStatus.IDLE:
                                    wlog.debug('[Agent] Worker %s IDLE, wake up worker' % worker_id)
                                    self.cond_list[worker_id].acquire()
                                    self.cond_list[worker_id].notify()
                                    self.cond_list[worker_id].release()
                                    count-=1
                                    if count == 0:
                                        break
                            self.list_lock.release()
                            self.task_acquire = False
                            continue
                        # remove task, v={flag:F/V, list:[tid]}
                        elif int(k) == Tags.TASK_REMOVE:
                            wlog.info('[WorkerAgent] Receive TASK_REMOVE msg = %s' % v)
                            self.removed_tasks.extend(v['list'])
                            for worker in self.worker_list.values():
                                if worker.running_task.tid in v['list']:
                                    tmptask = worker.running_task
                                    ret = worker.term_task(tmptask.tid, v['flag'])
                        # master disconnect ack
                        elif int(k) == Tags.LOGOUT:
                            wlog.info('[WorkerAgent] Receive LOGOUT msg = %s' % v)
                            self.list_lock.acquire()
                            for i in range(len(self.worker_list)):
                                if self.worker_status[i] == WorkerStatus.FINALIZED:
                                    self.cond_list[i].acquire()
                                    self.cond_list[i].notify()
                                    self.cond_list[i].release()
                            self.list_lock.release()
                            # TODO remove worker from list
                            #self.__should_stop = True
                            self.stop()
                            break
                        # force worker to stop
                        elif int(k) == Tags.WORKER_STOP:
                            wlog.info('[Agent] Receive WORKER_STOP msg = %s' % v)
                            self.fin_flag = True
                            self.list_lock.acquire()
                            for i in self.worker_status.keys():
                                if self.worker_status[i] == WorkerStatus.RUNNING:
                                    self.worker_list[i].terminate()
                                if self.worker_status[i] == WorkerStatus.IDLE:
                                    self.cond_list[i].acquire()
                                    self.cond_list[i].notify()
                                    self.cond_list[i].release()
                            self.list_lock.release()

                        # app finalize v=None/[Taskobj]
                        elif int(k) == Tags.APP_FIN:
                            wlog.info('[WorkerAgent] Receive APP_FIN msg = %s' % v)
                            self.tmpLock.acquire()
                            self.finExecutor = v
                            self.tmpLock.release()
                            self.app_fin_flag = True

                        elif int(k) == Tags.WORKER_HALT:
                            wlog.info('[Agent] Receive WORKER_HALT command')
                            self.halt_flag=True
                            #self.loop_time = 1
                        elif int(k) == Tags.EXTRA:
                            wlog.debug('[Agent] Receive time exam msg')
                            ele = Recoder.BaseElement(self.wid)
                            ele.cpurate=0
                            ele.cpuid = 0
                            ele.mem = 0
                            ele.delay = time.time()-v['ctime']
                            ele.extra = v['response']
                            self.recoder.set_message(self.wid,ele)

                        #code for control task
                        elif int(k) == Tags.TASK_CONTROL:
                            #control task status
                            wlog.info('[Agent] Receive task control status = %s' % v.boot[0])
                            if v.boot[0] == 'pause':
                                for i in range(len(self.worker_list)):
                                    self.worker_list[i].sniper.put_sniper_state(0);
                                wlog.info('[Agent] %s the sniper' % v.boot[0])

			    if v.boot[0] == 'continue':
                                for i in range(len(self.worker_list)):
                                    self.worker_list[i].sniper.put_sniper_state(1);
                                wlog.info('[Agent] %s the sniper' % v.boot[0])
				
			    if  v.boot[0] == 'terminate':
                                for i in range(len(self.worker_list)):
                                    self.worker_list[i].sniper.put_sniper_state(2);
                                wlog.info('[Agent] %s the sniper' % v.boot[0])

                        elif int(k) == Tags.TASK_EMPTY:
                            self.heartbeat.acquire_queue.put({Tags.TASK_ADD:1})

                #if self.initial_flag and len(self.worker_list) == 0 and not self.app_fin_flag:
                #    self.halt_flag = False
                #    self.heartbeat.acquire_queue.put({Tags.APP_FIN: {'wid': self.wid, 'recode': status.SUCCESS, 'result': None}})
                #    wlog.info('[Agent] Send APP_FIN msg for logout/newApp')
                #    self.app_fin_flag = True

                #ask for new task
                # ask for one task
                ask_flag = False
                for stu in self.worker_status.values():
                    if stu == WorkerStatus.IDLE:
                        ask_flag = True
                        break
                if not self.task_acquire and ask_flag and not self.fin_flag and len(self.worker_list) != 0:
                #if not self.task_acquire and self.task_queue.empty() and not self.fin_flag and len(self.worker_list) != 0:
                    if self.task_queue.empty() and self.worker_list[0].status == WorkerStatus.IDLE:
                        wlog.debug('[Agent] Worker need more tasks, ask for new task')
                        self.heartbeat.acquire_queue.put({Tags.TASK_ADD:1})
                        self.task_acquire = True

                # Finalize worker
                if self.app_fin_flag and self.task_queue.empty():
                    if len(self.worker_list) != 0:
                        wlog.debug('[Agent] Wait for worker thread join')
                        #TODO wait for all worker finalized, handle maybe finalize task infinte loop
                        wlog.debug('[Agent] set fin_flag for all workers')
                        self.list_lock.acquire()
                        for wid, worker in self.worker_list.items():
                            if self.worker_status[wid] != WorkerStatus.RUNNING and not worker.fin_flag:
                                worker.fin_flag = True
                            if self.worker_status[wid] == WorkerStatus.FINALIZE_FAIL:
                                wlog.info('[Agent] Worker %d finalize error, force stop'%wid)
                                self.worker_list[wid].terminate()
                            if self.worker_status[wid] == WorkerStatus.IDLE:
                                wlog.debug('[Agent] Wake up idle worker %d'%wid)
                                self.cond_list[wid].acquire()
                                self.cond_list[wid].notify()
                                self.cond_list[wid].release()
                        self.list_lock.release()
                        #time.sleep(0.1)
                    #else:
                    #    self.stop()
                    else:
                        wlog.debug('[Agent] Wait for master logout message')
                #wlog.debug('[Agent] All worker status = %s'%self.worker_status)

                #Worker Error, logout
                if self.fin_flag and len(self.worker_list) == 0:
                    self.stop()
            #self.stop()
            wlog.debug('[Agent] remains %d alive thread, [%s]' % (threading.active_count(), threading.enumerate()))
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.__should_stop = True
        wlog.info('[WorkerAgent] HeartBeat stop...')
        if self.heartbeat:
            self.heartbeat.stop()
            self.heartbeat.join()
        ret = self.client.stop(False)
        wlog.info('[WorkerAgent] Agent stop..., exit code = %d'%ret)
        if ret != 0:
            wlog.error('[WorkerAgent] Client stop error, errcode = %d'%ret)
            # TODO add solution

    def remove_worker(self,wid):
        self.list_lock.acquire()
        self.worker_list.pop(wid)
        self.worker_status.pop(wid)
        self.cond_list.pop(wid)
        self.list_lock.release()

    def getTask(self):
        if not self.task_queue.empty():
            return self.task_queue.get()
        else:
            return None

    def task_done(self,task):
        wlog.info('[Agent] Worker finish task %s' % (task.tid))
        self.task_completed_queue.put(task)

    def setup_done(self,wid,retcode,errmsg=None):
        
        self.status = WorkerStatus.INITIALIZED
        self.worker_status[wid] = WorkerStatus.INITIALIZED
        if not self.initial_flag:
            self.initial_flag = True
        wlog.info('[Agent] Feed back app init result')
        self.heartbeat.acquire_queue.put({Tags.APP_INI: {'recode': retcode, 'errmsg': errmsg}})

    def finalize_done(self,wid,retcode, errmsg=None):
        if retcode != 0:
            self.worker_status[wid] = WorkerStatus.FINALIZE_FAIL
            self.status = WorkerStatus.FINALIZE_FAIL
            wlog.error('[Agent-Error] Worker %s finalize error, error msg = %s' % (wid, errmsg))
        else:
            self.worker_status[wid] = WorkerStatus.FINALIZED
            self.status = WorkerStatus.FINALIZED
            self.remove_worker(wid)
            wlog.info('[Agent] Worker %s finalized, remove from list'%wid)
        self.heartbeat.acquire_queue.put({Tags.APP_FIN: {'recode':retcode,'errmsg':errmsg}})

    def getRuntasklist(self):
        rtask_list={}
        for worker in self.worker_list.values():
            rtask_list[worker.id]=[]
            if worker.running_task is not None:
                rtask_list[worker.id].append(worker.running_task.tid)
        #wlog.debug('[Agent] Running task = %s'%rtask_list)
        return rtask_list


    def _app_change(self,appid):
        pass

    def health_info(self):
        """
        Provide node health information which is transfered to Master
        Info: CPU-Usage, numProcessors, totalMemory, usedMemory
        Plug in self-costume bash scripts to add more information
        :return: dict
        """

        tmpdict = {}
        #------change to psutil--------
        '''
        cpuid1 = None
        cpuid2 = None
        if self.worker_list and self.worker_list[0].process:
            pid = self.worker_list[0].process.pid
            pid = str(pid)+' '+str(os.getpid())
            rc = subprocess.Popen(['ps -o pid,psr -p %s'%pid],stdout = subprocess.PIPE, stderr=subprocess.PIPE,shell=True)
            out,err = rc.communicate()
            #wlog.debug('[Agent] Worker Cpu Usage = %s'%out)
            #print out
            out = out.strip().split('\n')
            cpuid1 = out[-1].strip().split(' ')[-1]
            cpuid2 = out[-2].strip().split(' ')[-1]
        '''
                #------change to psutil------
        if not self.worker_list.has_key(0):
            return tmpdict
        proc = self.worker_list[0].sniper
        if not proc:
            return tmpdict
        proc = proc.process
        if not proc:
            return tmpdict
        child = proc.children(recursive=True)
        if not child:
            return tmpdict
        try:
            child = child[-1]
            tmpdict['CpuUsage'] = child.cpu_percent(interval=0.05)
            tmpdict['MemoUsage'] = HD.getMemoUsage()
            tmpdict['CpuId'] = child.cpu_num()
            tmpdict['extra'] = child.cmdline()
        except psutil.Error:
            return {}
        script = self.cfg.getCFGattr("health_detect_scripts")
        if script and os.path.exists(self.cfg.getCFGattr('topdir') + '/' + script):
            script = self.cfg.getCFGattr('topdir') + '/' + script
            rc = subprocess.Popen(executable=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            info, err = rc.communicate()
            if err == '':
                tmpdict['script_info'] = info
            else:
                tmpdict['script_err'] = err

        return tmpdict

    def set_status(self, wid, status):
        self.worker_status[wid] = status

    def get_status(self):
        return self.worker_status[0] if self.worker_status.has_key(0) else None



class Worker(BaseThread):
    def __init__(self,id, workagent, cond, config, name=None, worker_class=None):
        if not name:
            name = "worker_%s"%id
        BaseThread.__init__(self,name)
        self.cfg = config
        self.workeragent = workagent
        self.id = id
        self.running_task = None #TASK obj
        self.cond = cond
        self.initialized = False
        self.setup_flag = True
        self.finialized = False
        self.fin_flag = False
        self.status = WorkerStatus.NEW

        self.finish_task = None

        global wlog
        self.log = wlog

        self.worker_obj = None
        if worker_class:
            self.worker_obj = worker_class(self.log)
            self.log.debug('[Worker_%s] Create Worker object %s'%(self.id,self.worker_obj.__class__.__name__))
        #self.proc_log = open("%s/worker_%d.log"%(self.workeragent.cfg.getCFGattr("Rundir"),self.id),'w+')
        self.log.debug('[Worker_%s] Worker sniper log path:%s/worker_%d.log'%(self.id,self.workeragent.cfg.getCFGattr("rundir"),self.id))

        self.sniper = None
        self.recode = 0
        

    def setup(self):
        timeout = self.cfg.getCFGattr('task_answer_timeout')
        if timeout == 0:
            timeout=None
        wlog.info('[Worker_%s] Start to setup...' % self.id)
        self.sniper = SniperWorker(Config.Config.getCFGattr('rundir')+'/DistJET_log/sniper%d_%d.log'%(self.workeragent.wid,self.id),
                                   timeout=timeout,
                                   task_callback=self.task_done,
                                   finalize_callback=self.finalize_done,
                                   ignoreFail=Config.Config.getPolicyattr('ignore_task_fail'))
        self.initialized = True
        

    def do_task(self,task):
        self.running_task = task
        self.status = WorkerStatus.RUNNING
        self.workeragent.set_status(self.id, self.status)
        self.sniper.set_task(task)
        wlog.info("####task.boost = %s and task.id= %s ####"%(task.boot,task.tid))
        #comm_list = task.genCommand(self.log)
        #self.log.debug('[Worker_%d] Worker add task script:%s'%(self.id,comm_list))
        #if len(comm_list) != 0:
        #    self.sniper.set_exe(comm_list)
        #else:
        #    self.log.error('[Worker_%d] Task is empty, cannot execute. Task=<%s>'%(self.id,task.toDict()))

    def finalize(self, fin_task):
        self.log.debug('[Worker_%d] Ready to finalize, fin_task=%s'%(self.id,type(fin_task)))
        self.sniper.finalize_and_cleanup(fin_task)
        if fin_task is None or type(fin_task)==types.StringType:
            return 0
        else:
            return -1

    def terminate(self):
        self.sniper.stop(force=True)
        self.stop()

    def idle(self):
        self.status = WorkerStatus.IDLE
        self.workeragent.set_status(self.id,self.status)
        self.cond.acquire()
        self.cond.wait()
        self.cond.release()

    def task_done(self, stu, retcode, start_time, end_time, logfile_path):
        wlog.info('[Worker_%d] Task %s finish, status=%s'%(self.id, str(self.running_task.tid),ProcessStatus.describe(stu)))
        if stu == ProcessStatus.SUCCESS:
            self.running_task.complete(start_time,end_time)
            if logfile_path and logfile_path.endswith('.tmp'):
                os.rename(logfile_path,logfile_path[:-4])
        else:
            self.running_task.fail(start_time,end_time,ProcessStatus.describe(stu))
            if logfile_path and logfile_path.endswith('.tmp'):
                os.rename(logfile_path,logfile_path[:-3]+'err')
        self.finish_task = self.running_task
        #if self.status == WorkerStatus.IDLE:
        self.cond.acquire()
        self.cond.notify()
        self.cond.release()

    def finalize_done(self,stu, retcode, start_time,end_time,*kwd):
        wlog.info('[Worker_%d] Process finalize, status=%s'%(self.id,ProcessStatus.describe(stu)))
        if stu == ProcessStatus.SUCCESS:
            self.finialized = True
            self.status = WorkerStatus.FINALIZED
        else:
            self.status = WorkerStatus.FINALIZE_FAIL
        self.workeragent.finalize_done(self.id,retcode,ProcessStatus.describe(stu))


    def run(self):
        init_try = 0
        ret = 0
        while not self.get_stop_flag():
            while not self.initialized and not self.setup_flag:
                self.cond.acquire()
                self.cond.wait()
                self.cond.release()
            
            if not self.initialized:
                self.setup()
                self.workeragent.setup_done(self.id, 0, ProcessStatus.describe(0))
                self.sniper.start()
                
            if self.initialized:
                # ask for tasks
                tmptime=0 # times of ask tasks
                while not self.fin_flag:
                    task = self.workeragent.getTask()
                    if task is None:
                        tmptime+=1
                        if tmptime == 5:
                            tmptime = 0
                            self.idle()
                        continue
                    wlog.info( 'worker %d running task %d'%(self.id,task.tid))
                    self.do_task(task)
                    # wait for process return result
                    self.cond.acquire()
                    self.cond.wait()
                    self.cond.release()
                    self.running_task = None
                    self.workeragent.task_done(self.finish_task)
            
            wlog.debug('[Worker_%d] Finalize task = %s'%(self.id,self.workeragent.finExecutor))
            self.finalize(self.workeragent.finExecutor)
            if ret == ProcessStatus.SUCCESS:
                self.status = WorkerStatus.FINALIZING
            self.workeragent.set_status(self.id, self.status)
            while self.finialized:
                time.sleep(0.1)
            self.sniper.process.wait()
            wlog.info("[Worker_%d] Stop..."%self.id)
            self.stop()
        wlog.info('[Worker_%d] Exit run method'%self.id)



# For test
def dummy_master_run(agent):
    time.sleep(1)
    print ("<master> register success")
    initask = Task(0)
    initask.boot.append("source /afs/ihep.ac.cn/soft/juno/JUNO-ALL-SLC6/Pre-Release/J17v1r1-Pre2/setup.sh\n")
    value = Package.pack_obj({Tags.MPI_REGISTY_ACK:{'wid':'1','appid':1,'wmp':None,'init':[initask]}})
    pack = IM.Pack(Tags.MPI_REGISTY_ACK,len(value))
    pack.sbuf=value
    agent.recv_buff.put(pack)
    time.sleep(1)

    print ("<master> add task")
    task = Task(1)
    task.boot.append('echo "hello world"')
    value = Package.pack_obj({Tags.TASK_ADD: [task]})
    pack = IM.Pack(Tags.TASK_ADD, len(value))
    pack.sbuf = value
    agent.recv_buff.put(pack)
    time.sleep(1)

    print ("<master> finalize")
    value = Package.pack_obj({Tags.APP_FIN:None})
    pack = IM.Pack(Tags.APP_FIN,len(value))
    pack.sbuf = value
    agent.recv_buff.put(pack)
    time.sleep(10)

    value = Package.pack_obj({Tags.LOGOUT:None})
    pack = IM.Pack(Tags.APP_FIN,len(value))
    pack.sbuf = value
    agent.recv_buff.put(pack)


if __name__ == '__main__':
    workeragent = WorkerAgent("Test",capacity=2)
    master_thread = threading.Thread(target=dummy_master_run,args=(workeragent,))
    master_thread.start()
    workeragent.run()



