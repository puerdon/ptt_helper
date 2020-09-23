import ctypes, sys
import os



class PyWordSeg(object):
    def __init__(self, Library, inifile):
        self.lib = ctypes.cdll.LoadLibrary(Library)
        self.lib.WordSeg_InitData.restype=ctypes.c_bool
        self.lib.WordSeg_ApplyList.restype=ctypes.c_bool
        self.lib.WordSeg_GetResultBegin.restype=ctypes.c_wchar_p
        self.lib.WordSeg_GetResultNext.restype=ctypes.c_wchar_p
        self.obj = self.lib.WordSeg_New()
        ret = self.lib.WordSeg_InitData(self.obj, inifile.encode('utf-8'))
        if not ret:
            raise IOError("Loading %s failed."%(inifile))

    def EnableLogger(self):
        self.lib.WordSeg_EnableConsoleLogger(self.obj)

    def ApplyList(self, inputList):
        if len(inputList)==0:
            return []
        inArr=(ctypes.c_wchar_p*len(inputList))()
        inArr[:]=inputList
        ret=self.lib.WordSeg_ApplyList(self.obj, len(inputList), inArr)
        if ret==None:
            return []

        outputList=[]
        out=self.lib.WordSeg_GetResultBegin(self.obj)
        while out!=None:
            outputList.append(out)
            out=self.lib.WordSeg_GetResultNext(self.obj)
            
        return outputList

    def Destroy(self):
        self.lib.WordSeg_Destroy(self.obj)

def CKIP(ckipws_path):
    os.chdir(ckipws_path)
    return PyWordSeg('lib/libWordSeg.so', 'ws.ini')

