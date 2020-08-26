import threading

class T(threading.Thread):

    def __init__(self,a):
        super(T,self).__init__()
        self.a = a


thread = T(10)
print thread.start
