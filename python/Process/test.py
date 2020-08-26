import os
import errno

if __name__ == '__main__':
    try:
        os.setsid()
    except OSError, (err_no, err_message):
        print "os.setsid failed: errno=%d: %s"% (err_no, err_message)
        print "pid=%d  pgid=%d"%(os.getpid(), os.getpgid(os.getpid()))
