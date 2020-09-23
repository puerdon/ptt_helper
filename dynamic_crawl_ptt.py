from pathlib import Path
from datetime import datetime
from os import system
import sys

if __name__ == '__main__':

    # 資料所在資料夾
    data_dir = sys.argv[1]
    data_dir = Path(data_dir)

    # 要爬的版
    board = sys.argv[2]
    board_dir = data_dir / board

    # step 0: 檢查 data_dir 和 board 存不存在
    if not data_dir.is_dir() or not board_dir.is_dir():
        raise FileNotFoundError
        # TBD: 要給出錯誤訊息

    # step 1: 先找出該版中，存在本地中最新的資料
    latest_year = max([int(year.name) for year in board_dir.iterdir()])
    latest_year_dir = board_dir / str(latest_year)
    latest_timestamp = max([int(t.name[16:16+10]) for t in latest_year_dir.iterdir()])

    print(latest_year)
    print(latest_timestamp)
    print(datetime.fromtimestamp(latest_timestamp))
#
