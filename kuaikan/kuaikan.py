# -*- coding: utf-8 -*-

import os
import re
import urllib
import base64
import hashlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote


s = requests.Session()

preLoginUrl = 'https://login.sina.com.cn/sso/prelogin.php?entry=openapi&callback=sinaSSOController.preloginCallBack&su=MDA4ODY5MzgzNTIyNTA%3D&rsakt=mod&checkpin=1&client=ssologin.js(v1.4.18)&_=1556986279490'
loginUrl = 'https://api.weibo.com/oauth2/authorize?redirect_uri=https://www.kuaikanmanhua.com/v1/passport/login/pc/user_weibo_login_check&state=%257B%2522from%2522%253A%2522web%2522%252C%2522info%2522%253A%2522%2522%252C%2522redirectUrl%2522%253A%2522https://www.kuaikanmanhua.com/web/topic/2322/%2522%257D&client_id=3691583305'
topicUrl = 'https://www.kuaikanmanhua.com/web/topic/2322/'
prefixUrl = 'https://www.kuaikanmanhua.com/web/'

# loginUrl = 'https://login.sina.com.cn/sso/login.php?client=ssologin.js(v1.4.18)&_=1556998696182&openapilogin=qrcode'


# # 清空原haeaders
# s.headers.clear()
# # 更新headers
# s.headers.update(headers)


# soup = BeautifulSoup(r.text, "lxml")
# comic = soup.find_all('div', 'TopicItem cls')


def preLogin():
    url = preLoginUrl
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    # 清空原haeaders
    s.headers.clear()
    # 更新headers
    s.headers.update(headers)
    r = s.get(url)
    # r = s.post(url, data)
    servertime = r.text.split('servertime":')[1].split(',')[0]
    nonce = r.text.split('nonce":"')[1].split('"')[0]
    # print(nonce)
    return (servertime, nonce)


def get_susp(username, password, servertime, nonce):

    su = base64.b64encode(username.encode()).decode()

    sp = hashlib.sha1(str(password).encode('utf-8')).hexdigest()
    sp = hashlib.sha1(str(sp).encode('utf-8')).hexdigest()
    sp = password + servertime + nonce
    sp = hashlib.sha1(str(sp).encode('utf-8')).hexdigest()
    return (su, sp)


def login(su, servertime, nonce, sp):
    url = loginUrl,
    data = {
        'entry': 'openapi',
        'gateway': '1',
        'from': '',
        'savestate': '0',
        'useticket': '1',
        'pagerefer': '',
        'ct': '1800',
        's': '1',
        'vsnf': '1',
        'vsnval': '',
        'door': '',
        'appkey': '5X6DTb',
        'su': su,  # base64
        'service': 'miniblog',
        'servertime': servertime,
        'nonce': nonce,
        'pwencode': 'rsa2',
        'rsakv': '1330428213',
        'sp': sp,  # hash
        'sr': '1536*864',
        'encoding': 'UTF-8',
        'cdult': '2',
        'domain': 'weibo.com',
        'prelt': '261',
        'returntype': 'TEXT',
    }

    headers = {
        # 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3',
        # 'Accept-Encoding': 'gzip, deflate, br',
        # 'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6,ja;q=0.5,nl;q=0.4',
        # 'Cache-Control': 'max-age=0',
        # 'Connection': 'keep-alive',
        # 'Cookie': 'JSESSIONID=172AC64327C2E18E803FD0227DD5B0B0',
        # 'Host': 'api.weibo.com',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
    }

    s.headers.clear()
    s.headers.update(headers)
    # r = s.post(url, data=data)
    r = s.get(url)
    print(r.text)


comicUrl = []
comicName = []


def downloadComic():
    # login()
    url = topicUrl
    s.headers.clear()
    r = s.get(url)
    soup = BeautifulSoup(r.text, "lxml")
    comic = soup.find_all('div', 'TopicItem cls')

    # 漫畫連結
    for c in comic:
        cu = c.find('div', 'title fl')
        cu = str(cu).split('href="')[1].split("\n")[0]
        print(cu)
        comicUrl.append(str(cu))

    print(comicUrl)


if __name__ == '__main__':

    print('快看漫畫下載\n作者：rtshaw\n')
    # 登入並保存帳號
    servertime, nonce = preLogin()
    if os.path.isfile('./account.txt'):
        with open('./account.txt', 'r') as f:
            username = f.readline().strip()
            password = f.readline().strip()
    else:
        username = input("帳號：")
        password = input("密碼：")
        with open('./account.txt', 'w') as f:
            f.write('%s\n%s' % (username, password))
    print("\n開始嘗試登入\n")

    su, sp = get_susp(username, password, servertime, nonce)

    login(su, servertime, nonce, sp)
    # print(servertime, nonce)
    input('按任意鍵退出')
