import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from pyquery import PyQuery
from html.parser import HTMLParser




def html2json(html_path):
    """
    輸入： Path物件 (為.html檔的路徑)    
    
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
#             'order': i+1
        }

        comments.append(comment)


    return {
        "comments": comments,
        "post_vote": post_vote
    }

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
            json.dump(json_result, f, ensure_ascii=False)
