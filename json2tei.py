import json
import logging
import sys
import traceback
# from pathlib import Path
from datetime import datetime
from ckipws import CKIP

ckip = CKIP("/home/don/CKIPWS_Linux")

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


def _seg_and_pos(list_of_sentences, ckipws):
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
            
    del list_of_segmented_sentences
    
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
        return '\n'.join((f'<w type="{pos}">{word}</w>' for word, pos in list_of_list_of_tup[0]))
    else:
        result = "\n"
        for sentence in list_of_list_of_tup:
            result += "<s>\n"
            for word, pos in sentence:
                
                
                if word.startswith("http"):
                    continue
                
                if post_body:
                    result += f'                <w type="{pos}">{word}</w>\n'

                else:
                    result += f'                <w type="{pos}">{word}</w>\n'

            result += "</s>\n"
                
        return result


def json2tei(json_path):
    global ckip
    with open(json_path, 'r') as f:
        structured_post = json.load(f)
    
    post_id = structured_post["post_id"]
    post_author = structured_post["post_author"]
    post_board = structured_post["post_board"]
    
    
    if not isinstance(structured_post["post_time"], int):
        structured_post["post_time"] = int(structured_post["post_time"])
    dt = datetime.fromtimestamp(structured_post["post_time"])
    
    year = str(dt.year)
    month = str(dt.month)
    day = str(dt.day)
    neg = str(structured_post["post_vote"]["neg"])
    pos = str(structured_post["post_vote"]["pos"])
    neu = str(structured_post["post_vote"]["neg"])
    
    title_text = _render_tagged_tuple_to_string(_seg_and_pos([structured_post["post_title"]], ckip))
    
    body_text = _render_tagged_tuple_to_string(_seg_and_pos(_preprocessing_content(structured_post["post_body"]), ckip), post_body=True)
    
    comments_text = "\n"
    if len(structured_post['comments']) != 0:
        for c in structured_post['comments']:
            comment_author = c["author"]
            comment_type = c["type"]
#             comment_order = c["order"]
            comment_text = _render_tagged_tuple_to_string(_seg_and_pos([c["content"]], ckip))
            comments_text += f"""
<comment author="{comment_author}" c_type="{comment_type}">
<s>
{comment_text}
</s>
</comment>
"""
    
    return f"""<TEI.2>
    <teiHeader>
        <metadata name="author">{post_author}</metadata>
        <metadata name="post_id">{post_id}</metadata>
        <metadata name="year">{year}</metadata>
        <metadata name="board">{post_board}</metadata>
    </teiHeader>
    <text>
        <title author="{post_author}">
            <s>
                {title_text}
            </s>
        </title>
        <body author="{post_author}">
                {body_text}
        </body>
        {comments_text}
    </text>
</TEI.2>"""


def json2tei_wrapper(json_path):

    logging.info("開始處理: %s", json_path)

    # 即將要產生的.vrt檔路徑
    tei_path = json_path.with_suffix(".xml")

    # 如果該資料夾已經有 .json 檔了就跳過
    if tei_path.is_file():
        logging.info("-- 已存在tei(xml)檔: %s", tei_path)
        return

    try:
        tei_result = json2tei(json_path)

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

        with tei_path.open("w") as f:
            f.write(tei_result)