#!/usr/bin/env python
# coding: utf-8

# # 方便撈取的ptt語料的指令：
# 
# ## `list_{檔案副檔名}`: 列出各版各年份有幾篇
# 
# `
# $ python3 ptt_helper.py list_json|list_vrt -d <data_directory> (-b <board_name>)
# `
# 
# 若不指定<board_name>，則列出<data_directory>下各個版的資料夾中，各年份的文章有幾篇。
# 若指定<board_name>，則只列出<data_directory>/<board_name>下各年份的文章有幾篇。
# 
# 
# 
# ## `get_latest_post_timestamp`: 列出某板最新貼文時間
# `
# $ python3 ptt_helper.py get_latest_post_timestamp -d <data_directory> -b <board_name> 
# `
# 
# 找出路徑<data_directory>/<board_name>中，離現在最近的文章的timestamp。（用來動態更新爬蟲時，確定哪些時間的文章是還沒有的。）
# 
# 
# ## `html2json`: 將 .html 轉成 .json
# `
# $ python3 ptt_helper.py html2json -d <data_directory> (-b <board_name>) (--use-mp)
# `
# 
# 把<data_directory>下所有的文章的.html檔都改成json檔。（原本我的爬蟲是存成.html格式，後來發現這樣多佔用了很多空間。）
# 
# `--use-mp`: 啟動多進程模式
# 
# 
# ## `json2vrt`: 將 .json 轉成一個 .vrt [耗時因為斷詞]
# `
# $ python3 ptt_helper.py json2vrt -d <json檔所在資料夾> --use-mp
# `
# 
# ## `ws`: 測試斷詞
# `
# $ python3 ptt_helper.py ws <json_file_path>
# `
# 
# 斷詞
# 
# 
# ## `dynamic_crawl`: 動態更新ptt語料
# 
# `
# $ python3 ptt_helper.py dynamic_crawl -d <json檔所在資料夾>
# `
# 
# ## `reduce_to_one_vrt`: 將一個版的所有貼文的.vrt整合成一個.vrt
# 
# `
# python3 ptt_helper.py reduce_to_one_vrt -d <個別.vrt檔所在資料夾> -o <要輸出.vrt的資料夾>
# `
# 
# ## `save_lexical_items_to_mongo`: 掃過vrt，把詞彙資訊整理到mongodb中

# In[2]:


import os
import re
import json
import traceback
import sys
import argparse
from pathlib import Path
from datetime import datetime
import timeit
import logging
import multiprocessing as mp
from pymongo import MongoClient


import libtmux
from pyquery import PyQuery
from html.parser import HTMLParser

from html2vrt_new import parse_content
# from ckiptagger import data_utils, construct_dictionary, WS, POS, NER


# # `list`

# In[ ]:


def list_by_board_by_year(data_dir=None, board_name=None, ext="json"):
    
    if board_name is None:

        for board_dir in data_dir.iterdir():
            if board_dir.is_dir():
                print(f"[版名: {board_dir.name}]")
                
                iterate_year_dir_in_a_board_dir(board_dir, ext=ext)

    
    else:
        print(f"[{board_name}版]")
        iterate_year_dir_in_a_board_dir(data_dir / board_name, ext=ext)  


def iterate_year_dir_in_a_board_dir(board_dir, ext="json"):
#     total = 0
#     total_of_a_year = 0
    
    results = []
    # results 為 list of (int, int)
    
    for year_dir in board_dir.iterdir():

        if year_dir.is_file():
            continue
        

        total_of_a_year = len([p for p in year_dir.iterdir() if p.suffix ==  f".{ext}"])   
        results.append((int(year_dir.name), total_of_a_year))

    
    # 按照年份分類    
    results.sort(key=lambda x: x[0])
    
    # 算每一年的加總
    total = sum(number for (_, number) in results)
        
    for year, n in results:
        print(f"-- {year} 年: {n} 篇")
    print(f"----\n總計: {total}")


# #  `get_latest_post_timestamp`

# In[ ]:


def get_latest_post_timestamp(data_dir, board_name):
    
    board_dir = data_dir / board_name
    
    # step 0: 檢查 data_dir 和 board 存不存在
    if not data_dir.is_dir() or not board_dir.is_dir():
        raise FileNotFoundError
        # TBD: 要給出錯誤訊息

    # step 1: 先找出該版中，存在本地中最新的資料
    latest_year = max([int(year.name) for year in board_dir.iterdir()])
    latest_year_dir = board_dir / str(latest_year)
    latest_timestamp = max([int(t.name[16:16+10]) for t in latest_year_dir.iterdir()])

    return latest_timestamp


# # `html2json`

# In[ ]:


def html2json(html_path):
    """
    輸入： html格式的string
    
    輸出：
    - 如果 輸入中找不到 #main-content，或者沒有主文，回傳 None
    - 如果找得到，則正常回傳 parse 後的 post dict
    """
    
    with open(html_path, "r") as f:
        html = f.read()
    
    pq = PyQuery(html).make_links_absolute('https://www.ptt.cc/bbs/')

    html_pq_main_content = pq('#main-content')

    if len(html_pq_main_content) == 0:
        return None

    ###################
    # PARSE META DATA #
    ###################
    # po文的文章id, po文時間, po文所在的版
    post_id = html_path.stem.split('_')[-1]

    # po文的時間
    post_timestamp = re.search(r'\d{10}', str(html_path.stem)).group(0)
#     post_time = datetime.fromtimestamp(int(post_timestamp))

    # 在哪個版
    post_board = html_path.parent.parent.stem

    # 抓出meta: 作者/標題/時間
    meta = dict(
        (_.text(), _.next().text())
        for _
        in pq('.article-meta-tag').items()
    )

    ref = {
        '作者': 'author',
        '標題': 'title',
        '看板': 'board',
    }

    if '作者' in meta:
        post_author = meta['作者'].strip().split(' ')[0]
    else:
        post_author = ""

    if '標題' in meta:
        post_title = meta['標題'].strip()
    else:
        post_title = ""



    ######################
    # PARSE MAIN CONTENT #
    ######################

    body = mod_content(
        html_pq_main_content
        .clone()
        .children()
        .remove('span[class^="article-meta-"]')
        .remove('div.push')
        .end()
        .html()
    )

    if body == '' or body is None:
        return None

    # 篩掉引述的部分
    try:
        qs = re.findall('※ 引述.*|\n: .*', body)
        for q in qs:
            body = body.replace(q, '')
        body = body.strip('\n ')
    except Exception as e:
        print(e)

    ###################
    # PARSE COMMENTS  #
    ###################
    comments = parse_comments(pq)

    post = {
        "post_board": post_board,
        "post_id": post_id,
        "post_time": post_timestamp,
        "post_title": post_title,
        "post_author": post_author,
        "post_body": body,
        "post_vote": comments["post_vote"],
        "comments": comments["comments"]
    }


    return post

class MLStripper(HTMLParser):
    """HTML tag stripper.

    ref: http://stackoverflow.com/a/925630/1105489
    """

    def __init__(self):  # noqa
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.fed = []

    def handle_data(self, d):  # noqa
        self.fed.append(d)

    def get_data(self):  # noqa
        return ''.join(self.fed)

    @classmethod
    def strip_tags(cls, html):  # noqa
        s = cls()
        s.feed(html)
        return s.get_data()


def mod_content(content):
    """Remove unnecessary info from a PTT post."""
    content = MLStripper.strip_tags(content)
    content = re.sub(
        r"※ 發信站.*|※ 文章網址.*|※ 編輯.*", '', content
    ).strip('\r\n-')
    return content

def parse_comments(html_pq):
    """
    處理下方回文，將之結構化。
    
    input: PyQuery 物件
    
    Output: 
        如果沒有回文，回傳 dict {
            "comments": [],
            "post_vote": {
                "positive": <int>,
                "negative": <int>,
                "neutral": <int>
            }
        
        }
        
        如果有，則回傳 dict {
            "comments": [
                {
                    "author": <str>,
                    "type": <str: "neg", "pos", "neu">,
                    "content": <str>,
                    "order": <int>
                },
            ]
        }
    """
    comments = []
    post_vote = {
        "pos": 0,
        "neg": 0,
        "neu": 0
    }
    
    type_table = {
        "推": "pos",
        "噓": "neg",
        "→": "neu"
    }
    
    for i, _ in enumerate(html_pq('.push').items()):
        comment_type = _('.push-tag').text()
        
        # 總結
        if comment_type == "推":
            post_vote["pos"] += 1
        elif comment_type == "噓":
            post_vote["neg"] += 1
        elif comment_type == "→":
            post_vote["neu"] += 1
        else:
            continue

        comment = {
            'type': type_table[comment_type],
            'author': _('.push-userid').text().split(' ')[0],
            'content': _('.push-content').text().lstrip(' :'),
            'order': i+1
        }

        comments.append(comment)


    return {
        "comments": comments,
        "post_vote": post_vote
    }


# In[ ]:


def html2json_wrapper(html_path):
    logging.info("開始處理: %s", html_path)

    # 即將要產生的.json檔路徑
    json_path = html_path.with_suffix(".json")

    # 如果該資料夾已經有 .json 檔了就跳過
    if json_path.is_file():
        logging.info("-- 已存在json檔: %s", json_path)
        return

    try:
        json_result = html2json(html_path)

    except Exception as e:
        print(f"出問題檔案: {html_path}")
        print(f"錯誤訊息: {e}")
        logging.error("-- 執行 html2json() 出問題")
        logging.error("-- 錯誤訊息: %s", e)
   
    else:
        if json_result is None:
            logging.warning("-- 空白文!")
            return

        with json_path.open("w") as f:
            json.dump(json_result, f)


# # `json2vrt`

# In[17]:


def is_not_chinese_char(char):
    """
    Python port of Moses' code to check for CJK character.

    :param character: The character that needs to be checked.
    :type character: char
    :return: bool
    """
    return not (19968 <= ord(char) <= 40869)

def no_chinese_char_at_all(string):
    return all(map(is_not_chinese_char, string))

def _preprocessing_content(string):
    """
    將ptt內文作為字串，篩掉那些非中文字，並回傳真正要丟入斷詞的list of strings
    Input: content string
    Output: list of valid string
    """
    result = []
    
    for sentence in string.split():
        if not no_chinese_char_at_all(sentence.strip()):
            result.append(sentence.strip())
    return result


def _seg_and_pos(list_of_sentences):
    """
    input: <List of String>
    ["我每天都在睡覺", "好喜歡寫程式"]
    

    output: <List of List of (Str, Str)>
    [
        [
            ('我', 'Nb'),
            ('每天', 'P'),
            ...
        ],
        [
            ('好', 'D'),
            ('喜歡', 'V')
        ]
    ]
    """
#     result = list()
#     word_sentence_list = ws(
#         list_of_strings,
#         sentence_segmentation=True,
#     )
#     pos_sentence_list = pos(word_sentence_list)
#     for i, (list_of_word, list_of_pos) in enumerate(zip(word_sentence_list, pos_sentence_list)):
#         result.append(list())
#         for w, p in zip(list_of_word, list_of_pos):
#             result[i].append((w, p))
#     return result

    global ckipws

    list_of_segmented_sentences = None
    result = []
    
    # 先檢查輸入的list中，是否有空字串的元素

    indexs = []
    ls = map(str.strip, list_of_sentences)
    for i, elm in enumerate(ls):
        if not elm:  # 如果 elm 是 '' 空字串
            indexs.append(i)
    # 待會就用 len(indexs) 是否為 0 來判斷要不要後處理
    # 因為如果 ['', '我我', ''] 丟進中研院的斷詞系統
    # 回傳的結果會自動省略空字串變成 ['我(Nb)\n']

    try:
        list_of_segmented_sentences = ckipws.ApplyList(list_of_sentences)

    except Exception as e:
        print(e)
        return None
    
    for segmented_sentence in list_of_segmented_sentences:
        _r = []
        for word_and_pos in segmented_sentence.strip().split('\u3000'):
            wp = word_and_pos.split("(")
            word = wp[0]
            pos = wp[-1].strip().strip(")")
            
            if not word: # 偵測為 ( 的word
                word = '('
            
            _r.append((word, pos))
        result.append(_r)
            
            
    if len(indexs) > 0:
        for i in indexs:
            result.insert(i, [("NULL", "NULL")])
    
    return result


def _render_tagged_tuple_to_string(list_of_list_of_tup, post_body=False):
    """
    post_body: 如果是本文進來斷詞的話，因為本文是可以支援多行的，所以要在output時，要為每個句子的前後加上<s></s>
    
    Input: list of list of tuple
    [
        [
            ("我", "Nd"),
            ("跑", "VA"),
            ...
        ],
        ...
    ]
     
    Output: <str>
    
    我\tNd
    跑\tVA
    
    """
    
    if len(list_of_list_of_tup) == 0:
        return ""
    elif len(list_of_list_of_tup) == 1:
        # 如果是網址就不要出現
        if list_of_list_of_tup[0][0][0].startswith("http"):
            return ""
        return '\n'.join((f"{word}\t{pos}" for word, pos in list_of_list_of_tup[0]))
    else:
        result = "\n"
        for sentence in list_of_list_of_tup:
            result += "<s>\n"
            for word, pos in sentence:
                
                
                if word.startswith("http"):
                    continue
                
                if post_body:
                    result += f"{word}\t{pos}\n"
#                 s = '\n'.join((f"{word}\t{pos}" for word, pos in sentence))
#                 result += '\n<s>\n' + s + '\n</s>'
                else:
                    result += f"{word}\t{pos}\n"
#                     s = '\n'.join((f"{word}\t{pos}" for word, pos in sentence))
#                     result += s + '\n'
            result += "</s>\n"
                
        return result


def json2vrt(json_path):
    
    with open(json_path, 'r') as f:
        structured_post = json.load(f)
    
    post_id = structured_post["post_id"]
    post_author = structured_post["post_author"]
    
    if not isinstance(structured_post["post_time"], int):
        structured_post["post_time"] = int(structured_post["post_time"])
    dt = datetime.fromtimestamp(structured_post["post_time"])
    
    year = str(dt.year)
    month = str(dt.month)
    day = str(dt.day)
    neg = str(structured_post["post_vote"]["neg"])
    pos = str(structured_post["post_vote"]["pos"])
    neu = str(structured_post["post_vote"]["neg"])
    
    title_text = _render_tagged_tuple_to_string(_seg_and_pos([structured_post["post_title"]]))
    
    body_text = _render_tagged_tuple_to_string(_seg_and_pos(_preprocessing_content(structured_post["post_body"])), post_body=True)
    
    comments_text = "\n"
    if len(structured_post['comments']) != 0:
        for c in structured_post['comments']:
            comment_author = c["author"]
            comment_type = c["type"]
            comment_order = c["order"]
            comment_text = _render_tagged_tuple_to_string(_seg_and_pos([c["content"]]))
            comments_text += f"""
<text id="{post_id.replace('.', '_')}_comment_{comment_order}" type="comment" author="{comment_author}" c_type="{comment_type}">
<s>
{comment_text}
</s>
</text>
"""
    
    return f"""
<post id="{post_id}" year="{year}" month="{month}" day="{day}" neg="{neg}" pos="{pos}" neu="{neu}">
<text id="{post_id.replace('.', '_')}_title" type="title" author="{post_author}" c_type="NA">
<s>
{title_text}
</s>
</text>
<text id="{post_id.replace('.', '_')}_body" type="body" author="{post_author}" c_type="NA">
{body_text}
</text>
{comments_text}
</post>
"""


# In[ ]:


def json2vrt_wrapper(json_path):

    logging.info("開始處理: %s", json_path)

    # 即將要產生的.vrt檔路徑
    vrt_path = json_path.with_suffix(".vrt")

    # 如果該資料夾已經有 .json 檔了就跳過
    if vrt_path.is_file():
        logging.info("-- 已存在vrt檔: %s", vrt_path)
        return

    try:
        vrt_result = json2vrt(json_path)

    except Exception as e:
        print(f"出問題檔案: {json_path}")
        print(f"錯誤訊息: {e}")
        logging.error("-- 執行 json2vrt() 出問題")
        logging.error("-- 錯誤訊息: %s", e)
        error_class = e.__class__.__name__ #取得錯誤類型
        detail = e.args[0] #取得詳細內容
        cl, exc, tb = sys.exc_info() #取得Call Stack
        lastCallStack = traceback.extract_tb(tb)[-1] #取得Call Stack的最後一筆資料
        fileName = lastCallStack[0] #取得發生的檔案名稱
        lineNum = lastCallStack[1] #取得發生的行號
        funcName = lastCallStack[2] #取得發生的函數名稱
        errMsg = "File \"{}\", line {}, in {}: [{}] {}".format(fileName, lineNum, funcName, error_class, detail)
        print(errMsg)
   
    else:
#         if json_result is None:
#             logging.warning("-- 空白文!")
#             return

        with vrt_path.open("w") as f:
            f.write(vrt_result)


# # 斷詞

# In[12]:


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

        
def get_ckipws():
    os.chdir("/home/don/CKIPWS_Linux/lib")
    lib = '/home/don/CKIPWS_Linux/lib/libWordSeg.so'
    os.chdir("/home/don/CKIPWS_Linux")
    inifile = '/home/don/CKIPWS_Linux/ws.ini'

    return PyWordSeg(lib, inifile)


def initial():
    global ckipws
    
    os.chdir("/home/don/CKIPWS_Linux")
    lib = '/home/don/CKIPWS_Linux/lib/libWordSeg.so'
    inifile = '/home/don/CKIPWS_Linux/ws.ini'
    
    ckipws = PyWordSeg(lib, inifile)


# # 存進mongo

# In[ ]:


def save_to_mongo(vrt_file_path, collection):
    with open(vrt_file_path, "r") as file:
        for line in file:
            line = line.strip()
            if not line.startswith("<") and not line == "":
                _word_pos = line.split("\t")
                try:
                    word = _word_pos[0]
                    pos = _word_pos[1]
                except:
                    print("出錯的地方")
                    print(line)
                    print(_word_pos)

                collection.update_one(
                    {
                        "word": word,
                        "pos": pos,
                    },
                    {
                        "$inc": {
                            f"boards.{board_name}.": 1,
                            "total": 1
                        }
                    },
                    upsert=True
                )


# # `dynamic_crawl`

# In[1]:


if __name__ == '__main__':

    # 剖析指令和參數的部分
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", help="支援的指令:\n- list_by_board_by_year <data_directory> (<board_name>)\n- get_latest_post_timestamp <data_directory> <board_name> ")
    parser.add_argument("-d", "--data-dir", help="檔案所在資料夾路徑")
    parser.add_argument("-b", "--board", help="板名")
    parser.add_argument("-l", "--log-to", help=".log檔路徑檔名")
    
    
    # json2vrt才會用到的
#     parser.add_argument("-c", "--ckip-path", help="輸入ckiptagger的模型資料夾路徑")
    parser.add_argument("-o", "--output-dir", help="輸入要輸出的.vrt檔的完整路徑(含檔名)")
#     parser.add_argument("--use-gpu", help="是否使用gpu", action="store_true")
    parser.add_argument("--use-mp", help="如要使用多進程，請輸入這個參數", action="store_true")
    
    
    args = parser.parse_args()
    
    logging.basicConfig(
        format='%(asctime)s:%(levelname)s:%(message)s',
        level=logging.DEBUG,
        filename=args.log_to,
        filemode='w'
    )


    logging.info("呼叫指令：%s", args.cmd)
    logging.info("呼叫參數：%s", str(args))
    
    
    if args.data_dir is not None:
        data_dir = Path(args.data_dir)
    
    if args.cmd != "json2vrt" and args.cmd != "ws":
        print("接收到的參數:")
        print(f"- 要搜尋的資料夾: {data_dir.resolve()}")
        print(f"- 要搜尋的版: {args.board}")
        print("")

    
    if args.cmd.startswith("list"):
        ext = args.cmd.split("_")[1]
        list_by_board_by_year(data_dir=data_dir, board_name=args.board, ext=ext)
        
    elif args.cmd == "get_latest_post_timestamp":
        
        latest_timestamp = get_latest_post_timestamp(data_dir, args.board)
        logging.info(f"最新文章的timestamp: {latest_timestamp} ({datetime.fromtimestamp(latest_timestamp)})")
    
    
    
    elif args.cmd == "html2json":
        
        # 計時開始
        t1 = timeit.default_timer()
        
        # 如果有指定 --board 參數
        if args.board is not None:
            data_dir = data_dir / args.board 
        
        # 數總檔案數
        total_processed_files = len(list(data_dir.glob("**/*.html")))

        
        # 如果使用多進程
        if args.use_mp:

            cpu_count = mp.cpu_count()
            pool = mp.Pool(cpu_count)

            pool.imap_unordered(html2json_wrapper, data_dir.rglob("*.html"))

            pool.close()
            pool.join()
        
        
        # 如果不使用多進程
        else:
            for html_path in data_dir.rglob("*.html"):
                html2json_wrapper(html_path)
        
        # 計時屆結束  
        t2 = timeit.default_timer()
        
        print("=================")
        print(f"總處理檔案數: {total_processed_files}")
        print(f"總處理時間: {t2 -t1} 秒")
        logging.info("=================")
        logging.info(f"總處理檔案數: {total_processed_files}")
        logging.info(f"總處理時間: {t2 -t1} 秒")
    
    
    elif args.cmd == "json2vrt":
        
        ckipws = None
        initial()
        
        # 數總檔案數
        total_processed_files = len(list(data_dir.glob("**/*.json")))
        
        # 開始計時
        t1 = timeit.default_timer()


        # 使用多進程
        if args.use_mp:
            cpu_count = mp.cpu_count()
            pool = mp.Pool(cpu_count)
            pool.imap_unordered(json2vrt_wrapper, data_dir.rglob("*.json"))
            
            pool.close()
            pool.join()
            
        # 不使用多進程
        else:
            
            for json_path in data_dir.rglob("*.json"):
                json2vrt_wrapper(json_path)

        # 計時結束
        t2 = timeit.default_timer()   
        
        print("=================")
        print(f"總處理檔案數: {total_processed_files}")
        print(f"總處理時間: {t2 - t1} 秒")
        logging.info("=================")
        logging.info(f"總處理檔案數: {total_processed_files}")
        logging.info(f"總處理時間: {t2 - t1} 秒")

    
    elif args.cmd == "ws":
        
        
        def word_segmentation_ms_wrapper(list_of_sentences):
            ckipws = get_ckipws()
            a = ckipws.ApplyList(list_of_sentences)
            return a
            
#         lib = '/home/don/CKIPWS_Linux/lib/libWordSeg.so'
#         # 指定 CKIPWS 的設定檔
#         inifile = '/home/don/CKIPWS_Linux/ws.ini'
#         # 進行 CKIPWS 初始化的動作
#         initial(lib, inifile)

        
        t1 = timeit.default_timer()
        
        Result = word_segmentation_ms_wrapper(['這是一個測試的測試的'] * 1000)

        
        t2 = timeit.default_timer()
        print(t2 - t1)
        
        # 結果在 Result 中
#         print (Result)
    
    elif args.cmd == "dynamic_crawl":
        
        now = datetime.now()
        now_ymd_str = now.strftime("%Y_%m_%d")
        session_name = f"{now_ymd_str}_ptt_crawl"
        
        server = libtmux.Server()
        new_session = server.new_session(
            session_name=session_name,
            attach=False,
            start_directory="/home/don",
        )
        
        for board_path in data_dir.iterdir():
            board = board_path.name
            latest_timestamp = get_latest_post_timestamp(data_dir, board)
            
            logging.info(f"{board} 版: {datetime.fromtimestamp(latest_timestamp)}")
        
            window = new_session.new_window(attach=False, window_name=f"{board}")
            pane = window.split_window(attach=False)
            pane.send_keys("cd /home/don/ptt_python_crawler")
            pane.send_keys(f"scrapy crawl ptt_article -a boards={board} -a since={latest_timestamp} --logfile /home/don/log/{now_ymd_str}_{board} -a data_dir={str(data_dir)}")
#             pane.send_keys(f"python3 ptt_helper.py list_json -d /home/don/ptt_json_rawdata -b {board}")

            # 跑完後直接進行斷詞
            pane.send_keys(f"python3 /home/don/ptt_helper.py json2vrt -d {str(data_dir)} --use-mp")
    
    elif args.cmd == "reduce_to_one_vrt":
        
        for board_path in data_dir.iterdir():
            board = board_path.name
            
            output_dir = Path(args.output_dir)
            output_board_file = output_dir / f"{board}.vrt"
            
            with open(output_board_file, "w") as output_file:
                
                
                for individual_vrt_file in board_path.rglob("*.vrt"):
                    
                    with open(individual_vrt_file, "r") as f:
                        output_file.write(f.read() + "\n")
        
    elif args.cmd == "save_lexical_items_to_mongo":
        uri = "mongodb://ntulope:lopelopelopelope@localhost:27014/ptt?authSource=admin"
#         client = MongoClient(uri)

#         ptt_db = client.ptt
#         lexical_item_collection = ptt_db.lexical_item



#         for board_path in data_dir.iterdir():
#             board = board_path.name
            
#             save_to_mongo( vrt_file_path, lexical_item_collection)
        
    else:
        
        print("不存在這個指令！")


# In[94]:


#!jupyter nbconvert --to script ptt_helper.ipynb

