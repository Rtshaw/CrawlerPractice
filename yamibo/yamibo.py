# -*- coding: utf-8 -*-

# https://bbs.yamibo.com/forum-30-1.html

__author__ = 'rtshaw'
__date__ = '2020/02/08'
__version__ = '0.0.1'

import requests
import configparser
from bs4 import BeautifulSoup
import re
import os
import time
import threading

session = requests.Session()

member_url = 'https://bbs.yamibo.com/member.php?mod=logging&action=login&infloat=yes&frommessage&inajax=1&ajaxtarget=messagelogin'
base_url = 'https://bbs.yamibo.com/'


def get_hash():
    """獲取登入hash"""

    url = member_url
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
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
    url = f'https://bbs.yamibo.com/member.php?mod=logging&action=login&loginsubmit=yes&frommessage&loginhash={hash_["loginhash"]}&inajax=1'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
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


def mkdir(comic_title):
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


def get_comic_image(index, image_url, comic_title):
    """取得漫畫的圖片檔
    :param index: 索引（圖片名稱）
    :param Image_url: 圖片網址
    """
    url = f'{base_url}{image_url}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    response = session.get(url, headers=headers)
    time.sleep(0.2)

    word_directory = os.getcwd()

    with open(word_directory + f'\\Comic\\{comic_title}\\{index}.jpg', 'wb') as w:
        w.write(response.content)
        print(f'{comic_title} . {index}.jpg, ...OK ')


def download_comic(comic_number):
    """下載漫畫
    :param comic_number: 網頁代碼
    """
    url = f'https://bbs.yamibo.com/thread-{comic_number}-1-1.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    response = session.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'lxml')
    comic_title = soup.find('span', id='thread_subject').text
    comic_title.replace(':', '').replace(
        '/', '.').replace('|', '.')  # 避免資料夾無法使用之特殊字元

    mkdir(comic_title)

    # ignore標籤
    ignore_js_ops = soup.find_all('ignore_js_op')

    for i, ignore_tag in enumerate(ignore_js_ops):
        image = ignore_tag.find('img')['file']
        get_comic_image(i, image, comic_title)


def thread():
    """多線程"""

    comic_pages = int(input('要下載幾個頁面？'))
    print("\n說明：\n以 https://bbs.yamibo.com/thread-475959-1-1.html 為例，475959 為網頁代碼。\n")

    comic_list = list()

    for comic in range(comic_pages):
        comic_num = input(f'第 {comic+1} 個網頁代碼：')
        comic_list.append(comic_num)

    threads = list()
    for i, comic in enumerate(comic_list):
        threads.append(threading.Thread(target=download_comic, args=(comic,)))
        threads[i].start()


if __name__ == "__main__":

    print('百合會(300)漫畫下載\n作者：rtshaw\n')
    config = configparser.ConfigParser()
    config.read('config.ini')

    hash_ = get_hash()
    login(hash_, config['User1']['username'], config['User1']['password'])

    # 抓漫畫
    thread()
