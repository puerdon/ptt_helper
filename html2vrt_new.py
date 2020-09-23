
# coding: utf-8

# In[62]:


from pyquery import PyQuery
import os
import re
from datetime import datetime
from ckiptagger import data_utils, construct_dictionary, WS, POS, NER
from xml.etree.ElementTree import Element, SubElement, Comment, tostring
from xml.dom import minidom
import glob
import argparse
import multiprocessing as mp


# # Comment parser (from scraptt)

# # Post parser (from scraptt)

# In[63]:


# -*- coding: utf-8 -*-
"""PTT POST parsers."""
import re
from html.parser import HTMLParser


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
    try:
        content = MLStripper.strip_tags(content)
        content = re.sub(
            r"※ 發信站.*|※ 文章網址.*|※ 編輯.*", '', content
        ).strip('\r\n-')
        
        # 去除IP
        content = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "", content)
    except:
        print(content)
    return content


def extract_author(string):
    """
    抽取使用者的id，input範例 "lope (這是暱稱)"
    此函數目的在於去除括號的暱稱部分，只留下真正的user id
    Input: str
    Output: str
    """
    return string.split(' ')[0]


# # Parse html

# # parse content

# In[64]:


def parse_content(html_path):
    """
    抓出主文
    
    輸入: html檔的路徑
    輸出: 
        
    如果是完整的，回傳dict:
    {
        "post_board": <str>,
        "post_id": <str>,
        "post_time": <datetime>,
        "post_title": <str>,
        "post_author": <str>,
        "post_body": <str>,
        "post_vote": {
            "positive": <int>,
            "dnegative": <int>,
            "neutral": <int>
        },
        "comments": [
            {
                "author": <str>,
                "body": <str>,
                "type": <str: "neg", "pos", "neu">,
                "order": <int>
                
            }
        ]
        
    }
    
    如果是要略過的，則回傳 None
    """
    
    # init
    post = {}
    
    # 先將檔案讀進來
    with open(html_path, "r") as f:
        html_file = f.read()
    
    # 轉換成 PyQuery object
    html_pq = PyQuery(html_file)
    
    # TBD:
    # 要先把已刪除/錯誤的文章給篩掉
    # 像是篩掉那些沒有 .main-content or .article-meta-tag
    html_pq_main_content = html_pq('#main-content')
    if len(html_pq_main_content) == 0:
        return None
    
    ###################
    # PARSE META DATA #
    ###################
    
    
    # 檔名就有發表日期時間 & 文章ID的資訊
    ## 先取得檔名
    file_name = os.path.basename(html_path)
    # e.g. "20050812_1445_M.1123829150.A.584.html"
    ## 然後根據檔名找出日期時間 
    post_id = file_name.split("_")[-1][:-5]
    post_time = datetime.fromtimestamp(int((re.findall(r"(\d{10})", post_id)[0])))
    
    # 在哪個版
    post_board = html_pq('#topbar a.board').remove('span').text().strip()
    

    # 抓出meta: 作者/標題/時間
    meta = dict(
        (_.text(), _.next().text())
        for _
        in html_pq('.article-meta-tag').items()
    )

    
    ref = {
        '作者': 'author',
        '標題': 'title',
        '看板': 'board',
    }

    if '作者' in meta:
        post_author = extract_author(meta['作者'].strip())
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
    comments = parse_comments(html_pq)
    
    post = {
        "post_board": post_board,
        "post_id": post_id,
        "post_time": post_time,
        "post_title": post_title,
        "post_author": post_author,
        "post_body": body,
        "meta": meta,
        "post_vote": comments["post_vote"],
        "comments": comments["comments"]
    }

    
    return post


# In[65]:


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
            'author': extract_author(_('.push-userid').text()),
            'content': _('.push-content').text().lstrip(' :'),
            'order': i+1
        }

        comments.append(comment)


    return {
        "comments": comments,
        "post_vote": post_vote
    }


# In[66]:


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


# In[67]:


def _preprocessing_content(string):
    """
    將ptt內文作為字串，篩掉那些非中文字，並回傳真正要丟入斷詞的list of strings
    Input: content string
    Output: list of valid string
    """
    result = []
    for sentence in string.split("\n"):
        if not no_chinese_char_at_all(sentence.strip()):
            result.append(sentence.strip())
    return result


# In[68]:


def _seg_and_pos(list_of_strings):
    """
    input: ["我每天都在睡覺", "好喜歡寫程式"]
    
        word_sentence_list= [[我, 每天, 都, 在, 睡覺], [好, 喜歡, 寫, 城市]]
    
    output:
    [
        ()
    ]
    """
    result = list()
    word_sentence_list = ws(
        list_of_strings,
        sentence_segmentation=True,
    )
    pos_sentence_list = pos(word_sentence_list)
    for i, (list_of_word, list_of_pos) in enumerate(zip(word_sentence_list, pos_sentence_list)):
        result.append(list())
        for w, p in zip(list_of_word, list_of_pos):
            result[i].append((w, p))
#     return result
    return result


# In[75]:


def _render_tagged_tuple_to_string(list_of_list_of_tup):
    """
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
        return '\n'.join((f"{word}\t{pos}" for word, pos in list_of_list_of_tup[0]))
    else:
        result = ""
        for sentence in list_of_list_of_tup:
            s = '\n'.join((f"{word}\t{pos}" for word, pos in sentence))
            result += s + '\n'
        return result
    
#     if not clean:
#         return '\n'.join((f"{word}\t{pos}" for word, pos in tup_of_tup))
#     else:
#         result = ""
#         for word, pos in tup_of_tup:
#             word = word.replace("\n", "")
#             if word == "":
#                 continue
#             else:
#                 result += f"{word}\t{pos}\n"
#         return result


# # structured_post -> XML

# In[77]:


def structured_post_2_xml(structured_post):
    if structured_post is None:
        return ""
    
    post_id = structured_post["post_id"]
    post_author = structured_post["post_author"]
    year = str(structured_post["post_time"].year)
    month = str(structured_post["post_time"].month)
    day = str(structured_post["post_time"].day)
    neg = str(structured_post["post_vote"]["neg"])
    pos = str(structured_post["post_vote"]["pos"])
    neu = str(structured_post["post_vote"]["neg"])
    
    title_text = _render_tagged_tuple_to_string(_seg_and_pos([structured_post["post_title"]]))
    
    #print(title_text)
    
    body_text = _render_tagged_tuple_to_string(_seg_and_pos(_preprocessing_content(structured_post["post_body"])))
    
    #print(body_text)
    
    comments_text = "\n"
    if len(structured_post['comments']) != 0:
        for c in structured_post['comments']:
            comment_author = c["author"]
            comment_type = c["type"]
            comment_order = c["order"]
            comment_text = _render_tagged_tuple_to_string(_seg_and_pos([c["content"]]))
            comments_text += f"""
<text id="{post_id.replace('.', '_')}_comment_{comment_order}" type="comment" author="{comment_author}" c_type="{comment_type}">
{comment_text}
</text>
"""
    
    return f"""
<post id="{post_id}" year="{year}" month="{month}" day="{day}" neg="{neg}" pos="{pos}" neu="{neu}">
<text id="{post_id.replace('.', '_')}_title" type="title" author="{post_author}" c_type="NA">
{title_text}
</text>
<text id="{post_id.replace('.', '_')}_body" type="body" author="{post_author}" c_type="NA">
{body_text}
</text>
{comments_text}
</post>
"""


# In[60]:


def html_2_vrt(html_path):
    return structured_post_2_xml(parse_content(html_path))


# # multiprocessing

# In[1]:


def x(q):
    return q+1


# In[41]:


def mp_handler(output_path=None, glob_iter=None):
    p = mp.Pool()
    with open(output_path, "w") as f:
        for result in p.imap(html_2_vrt, glob_iter, chunksize=10):
            print(result)
            f.write(result)


# # __main__

# In[43]:


if __name__ == "__main__":
    ws = None
    pos = None
    
    parser = argparse.ArgumentParser(description="將一路徑底下的.html檔全部輸出到一個.vrt檔")
    parser.add_argument("-c", "--ckip-path", help="輸入ckiptagger的模型資料夾路徑", required=True)
    parser.add_argument("--output", help="輸入要輸出的.vrt檔的完整路徑(含檔名)", required=True)
    parser.add_argument("--html-path", help="輸入.html檔所在路徑", required=True)
    
    parser.add_argument("--use-gpu", help="如要使用GPU，請輸入這個參數", action="store_true")
    parser.add_argument("--use-mp", help="如要使用多進程，請輸入這個參數", action="store_true")
    args = parser.parse_args()
    
    # 是否使用 gpu 決定如何初始化 WS 和 POS
    if args.use_gpu:
        ws = WS(args.ckip_path, disable_cuda=False)
        pos = POS(args.ckip_path, disable_cuda=False)
    else:
        ws = WS(args.ckip_path, disable_cuda=True)
        pos = POS(args.ckip_path, disable_cuda=True)
    
    t1 = datetime.now()
    
    # 是否使用多進程
    if args.use_mp:
        # 加 filter() 確保是 .html 檔
        glob_iter = filter(lambda x: x.endswith(".html"), glob.iglob(f"{args.html_path}/**", recursive=True))
        mp_handler(output_path=args.output, glob_iter=glob_iter)
    else:
        with open(args.output, "w") as f:
            for root, _, files in os.walk(args.html_path):
                for file in files:
                    if file.endswith("html"):
                        path = os.path.join(root, file)
                        f.write(html_2_vrt(path))
    
    t2 = datetime.now()
    print(t2 - t1)
        

