# -*- coding: utf-8 -*-

# https://bbs.yamibo.com/forum-30-1.html

__author__ = 'casey'
__date__ = '2020/02/08'
__version__ = '0.0.2'

import configparser
import re
import os
import time
import threading
import pickle

import requests
from bs4 import BeautifulSoup
from opencc import OpenCC

session = requests.Session()

member_url = 'https://bbs.yamibo.com/member.php?mod=logging&action=login&infloat=yes&frommessage&inajax=1&ajaxtarget=messagelogin'
base_url = 'https://bbs.yamibo.com/'
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'

s2t = OpenCC('s2t') # 簡體字轉繁體字


def get_hash():
    """獲取登入hash"""

    url = member_url
    headers = {
        'User-Agent': ua,
    }
    session.headers.clear()  # 清空原haeaders
    session.headers.update(headers)  # 更新headers
    response = session.get(url)
    soup = BeautifulSoup(response.text, 'lxml')
    # 獲取formhash
    input_tags = soup.find_all('input')
    formhash = input_tags[0]['value']
    loginhash = input_tags[2]['id'].split('_')[1]

    hash_ = {
        'loginhash': loginhash,
        'formhash': formhash
    }
    return hash_


def login(hash_, username, password):
    """模擬登入
    :param hash_: hash
    :param username: 登入帳號
    :param password: 登入密碼
    """
    url = f'https://bbs.yamibo.com/member.php?\
        mod=logging&action=login&loginsubmit=yes&frommessage&loginhash={hash_["loginhash"]}&inajax=1'
    headers = {
        'User-Agent': ua,
    }
    data = {
        'formhash': hash_['formhash'],
        'referer': 'https://bbs.yamibo.com/forum-30-1.html',
        'loginfield': 'username',
        'username': username,
        'password': password,
        'questionid': 0,
        'answer': '',
    }
    response = session.post(url, headers=headers, data=data)
    if re.search('欢迎您回来', response.text):
        print(f'{username} 登入成功')
        # 保存 cookie 到文件
        with open('cookies.pkl', 'wb') as cookie_file:
            pickle.dump(session.cookies, cookie_file)
    else:
        print('登入失敗')

def load_cookies():
    """載入之前保存的 cookie"""
    try:
        with open('cookies.pkl', 'rb') as cookie_file:
            cookies = pickle.load(cookie_file)
            session.cookies.update(cookies)
            print('載入已有 cookie')
    except FileNotFoundError:
        print('没有找到保存的 cookie，需要重新登入')

def check_cookie_validity():
    """確認 cookie 是否有效"""
    # 发起一个简单的请求，检查是否登录
    response = session.get('https://bbs.yamibo.com/forum-30-1.html')
    if '欢迎您回来' in response.text:
        print('Cookie 有效')
        return True
    else:
        print('Cookie 無效')
        return False


def mkdir(comic_title):
    mode = config['System']['mode']
    if mode == 'on':
        work_directory = config['System']['path']
    else:
        work_directory = os.getcwd()

    if os.path.exists(work_directory+'\\Comic\\'):
        if os.path.exists(work_directory + f'\\Comic\\{comic_title}'):
            print(f'{comic_title} 資料夾已存在，進行下一步。')
        else:
            os.makedirs(work_directory + f'\\Comic\\{comic_title}')
            print(f'{comic_title} 資料夾，創建完成。')
    else:
        os.makedirs(work_directory + f'\\Comic\\{comic_title}')
        print(f'漫畫資料夾 與 {comic_title} 資料夾，創建完成。')


def get_comic_image(index, image_url, comic_title, mod=1):
    """取得漫畫的圖片檔
    :param index: 索引（圖片名稱）
    :param Image_url: 圖片網址
    :param comic_title: 漫畫名
    :param mod: 抓取模式
    """
    url = f'{base_url}{image_url}'
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": ua,
        "cookie": "EeqY_2132_saltkey=GLG5EoZG; EeqY_2132_lastvisit=1741140274; EeqY_2132_auth=6d14W%2FeTS%2BiLniPeGlIUhrKJoveqUDY%2BgjgzoHiv9r83pQ%2FBKCEr3RHcpC9wX5gBOUYB6ysF81jPr2lMMBHQ1HCFtpY; EeqY_2132_lastcheckfeed=141815%7C1741143878; EeqY_2132_member_login_status=1; EeqY_2132_visitedfid=30; EeqY_2132_smile=1D1; EeqY_2132_st_t=141815%7C1741144541%7C11e30260b0e4cb12d7c4e8b4670903fb; EeqY_2132_forum_lastvisit=D_30_1741144541; EeqY_2132_zqlj_sign_141815=20250306; EeqY_2132_ulastactivity=76c9SzDVY8YCfoPODPUPhlj9NwSpeT5p5YryY%2FNBfYmOx%2FO4w62d; EeqY_2132_sid=CyByzJ; EeqY_2132_lip=59.126.31.245%2C1741246576; EeqY_2132_home_diymode=1; EeqY_2132_viewid=tid_525800; EeqY_2132_lastact=1741250553%09forum.php%09viewthread; EeqY_2132_st_p=141815%7C1741250553%7C95a3784d5f8737677163c6e6e91590fb",
        "Referer": "https://bbs.yamibo.com/"
    }
    response = session.get(url, headers=headers)
    time.sleep(0.2)

    mode = config['System']['mode']
    if mode == 'on':
        work_directory = config['System']['path']
    else:
        work_directory = os.getcwd()

    with open(work_directory + f'\\Comic\\{comic_title}\\{index}.jpg', 'wb') as w:
        w.write(response.content)
        print(f'{comic_title} . {index}.jpg, ...OK ')


def download_comic(comic_url):
    """下載漫畫
    :param comic_url: 網頁代碼
    """
    url = comic_url
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": ua,
        "cookie": "EeqY_2132_saltkey=GLG5EoZG; EeqY_2132_lastvisit=1741140274; EeqY_2132_auth=6d14W%2FeTS%2BiLniPeGlIUhrKJoveqUDY%2BgjgzoHiv9r83pQ%2FBKCEr3RHcpC9wX5gBOUYB6ysF81jPr2lMMBHQ1HCFtpY; EeqY_2132_lastcheckfeed=141815%7C1741143878; EeqY_2132_member_login_status=1; EeqY_2132_visitedfid=30; EeqY_2132_smile=1D1; EeqY_2132_st_t=141815%7C1741144541%7C11e30260b0e4cb12d7c4e8b4670903fb; EeqY_2132_forum_lastvisit=D_30_1741144541; EeqY_2132_zqlj_sign_141815=20250306; EeqY_2132_ulastactivity=76c9SzDVY8YCfoPODPUPhlj9NwSpeT5p5YryY%2FNBfYmOx%2FO4w62d; EeqY_2132_sid=CyByzJ; EeqY_2132_lip=59.126.31.245%2C1741246576; EeqY_2132_home_diymode=1; EeqY_2132_viewid=tid_525800; EeqY_2132_lastact=1741250553%09forum.php%09viewthread; EeqY_2132_st_p=141815%7C1741250553%7C95a3784d5f8737677163c6e6e91590fb"
    }
    response = session.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'lxml')
    comic_title = soup.find('span', id='thread_subject').text
    comic_title = re.sub('[\\/:*?"<>|]', ' ', comic_title)  # 避免資料夾無法使用之特殊字元
    comic_title = comic_title.replace('(', '（').replace(')', '）') # 改為全形
    
    try:
        comic_title.encode('big5hkscs')
    except:
        comic_title = s2t.convert(comic_title) # 轉為繁體標題

    mkdir(comic_title)

    image_area = soup.find('div', class_='t_fsz')
    imgs = image_area.find_all('img', class_='zoom')
    if len(imgs)>0:
        for i, img_tag in enumerate(imgs):
            image = img_tag['file']
            if re.search('^data', image):
                get_comic_image(i, image, comic_title)
            else:
                get_comic_image(i, image, comic_title, 2)
    else:
        imgs = image_area.find_all('img')
        for i, img_tag in enumerate(imgs):
            image = img_tag['src']
            get_comic_image(i, image, comic_title, 2)

def thread():
    """多線程"""

    comic_pages = int(input('要下載幾個頁面？'))
    print("\n說明：\n請複製整段網址。\n")

    comic_list = []

    for comic in range(comic_pages):
        comic_num = input(f'第 {comic+1} 個網頁網址：')
        comic_list.append(comic_num)

    threads = []
    for i, comic in enumerate(comic_list):
        threads.append(threading.Thread(target=download_comic, args=(comic,)))
        threads[i].start()


if __name__ == "__main__":

    print('百合會(300)漫畫下載\n作者：rtshaw\n')
    config = configparser.ConfigParser()
    config.read('config.ini')

    load_cookies()
    if not check_cookie_validity():
        hash_ = get_hash()
        login(hash_, config['User1']['username'], config['User1']['password'])


    # 抓漫畫
    thread()
