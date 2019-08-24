# -*- coding: utf-8 -*-

import os
import re
import time
import requests
from bs4 import BeautifulSoup

s = requests.Session()

basic_url = 'https://www.popo.tw/'
# articles_url = 'https://www.popo.tw/books/197688/articles'

def get_articles(articles_url):
    url = articles_url
    re_url = re.compile('https://www.popo.tw/books/[0-9]+')
    url = re_url.match(url).group(0) + '/articles'

    headers = {
        'Cookie': 'authtoken6=1; bgcolor=bg-default; __gads=ID=7c9d2eef64b9258f:T=1565868094:S=ALNI_MabqlIAoCVZtentZiwvRzo8af6vqw; authtoken1=aGFpYmFyYTgwMTQz; word=select-L; __utmz=204782609.1566105490.153.7.utmcsr=members.popo.tw|utmccn=(referral)|utmcmd=referral|utmcct=/apps/login.php; PORF_TK001=9d6ca8da63e420ba2ba890bae93d142a438b6639s%3A40%3A%22881c4ae2dc133d610a8feae33c8fc9dca2b6e1c6%22%3B; __utmc=204782609; book18limit_686991=1362a390f19919863d5ed7b50bcbf274e05e8019s%3A1%3A%221%22%3B; _paabbdd=q7g2m696j9tisjgjunvcej44p3; __utma=204782609.1046002008.1556649297.1566397371.1566472727.167; __utmt=1; __utmb=204782609.5.10.1566472727; url=https%3A%2F%2Fwww.popo.tw%2Fbooks%2F197688%2Farticles; authtoken2=N2Q5NDQ2ZjVmZGY0ZTcyZGQxMDY5NGI3MTQ3MWE3ZGU%3D; authtoken3=2139207809; authtoken4=414722330; authtoken5=1566472818',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.100 Safari/537.36'
    }

    s.headers.clear()
    s.headers.update(headers)
    r = s.get(url)

    soup = BeautifulSoup(r.text, 'lxml')

    title = soup.find_all('h3')[0].get_text().split(' ')[0] # 作品名稱
    author = soup.find_all(class_ = 'b_author')[0].find('a').get_text() # 作者
    mkdir(author, title)
    intro_title = soup.find_all('h3')[1].get_text() # 作品內容簡介標題
    intro = soup.find_all(class_='book_intro')[0].find_all('span') # 作品內容簡介

    for i in intro:
        # print(i.get_text())
        with open(('./%s/%s/0000' %(author, title) + ' - %s.txt' %intro_title) , 'a+', encoding='utf-8') as f:
            f.write(i.get_text())
        f.close()
    links = soup.find_all(class_ = 'cname')
    number = soup.find_all(class_ = 'c1')

    link_list = []
    chap = []
    number_list = []
    for n in number:
        number_list.append(str(n).split('>')[1].split('<')[0])

    for l in links:
        link_list.append(str(l).split('"')[3]) # 小說網址
        chap.append(str(l).split('>')[1].split('<')[0]) # 小說章節名稱
        
    
    index = 0
    for index in range(0, len(link_list)):
        chap_url = basic_url + link_list[index]
        # print(url)
        get_chapter(chap_url, number_list[index], author, chap[index], title)

    # print(r.text)
    # print(links)

def get_chapter(c_url, number, author, chapname, title):
    url = c_url
    headers = {
        'Cookie': 'authtoken6=1; bgcolor=bg-default; __gads=ID=7c9d2eef64b9258f:T=1565868094:S=ALNI_MabqlIAoCVZtentZiwvRzo8af6vqw; authtoken1=aGFpYmFyYTgwMTQz; word=select-L; __utmz=204782609.1566105490.153.7.utmcsr=members.popo.tw|utmccn=(referral)|utmcmd=referral|utmcct=/apps/login.php; PORF_TK001=9d6ca8da63e420ba2ba890bae93d142a438b6639s%3A40%3A%22881c4ae2dc133d610a8feae33c8fc9dca2b6e1c6%22%3B; __utmc=204782609; book18limit_686991=1362a390f19919863d5ed7b50bcbf274e05e8019s%3A1%3A%221%22%3B; _paabbdd=q7g2m696j9tisjgjunvcej44p3; __utma=204782609.1046002008.1556649297.1566397371.1566472727.167; __utmt=1; __utmb=204782609.5.10.1566472727; url=https%3A%2F%2Fwww.popo.tw%2Fbooks%2F197688%2Farticles; authtoken2=N2Q5NDQ2ZjVmZGY0ZTcyZGQxMDY5NGI3MTQ3MWE3ZGU%3D; authtoken3=2139207809; authtoken4=414722330; authtoken5=1566472818',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.100 Safari/537.36'
    }
    s.headers.clear()
    s.headers.update(headers)
    r = s.get(url)
    time.sleep(1) # 防止請求過快

    soup = BeautifulSoup(r.text, 'lxml')
    contents = soup.find_all('p')

    for c in contents:
        # print(c.get_text())
        with open('./%s/%s/%s - %s.txt' %(author, title, number, chapname), 'a+', encoding='utf-8') as f:
            f.write(c.get_text()+'\n\n')
        f.close()
        print('[INFO] %s - %s.txt ...OK' %(number, chapname))

    # print(contents)
    # contents = soup.find_all(class_ = 'read-txt')
    # content_list = []
    # for c in contents:
    #     # print(c)
    #     print(str(c).split('<p>'))


# 建立資料夾
def mkdir(authorName, novelName):
    if os.path.exists(authorName):
        print("\n%s 資料夾已存在，開始下一步\n" %authorName)
        if os.path.exists('%s/%s' %(authorName,novelName)):
            print("%s 資料夾已存在，開始下一步\n" %novelName)
        else:
            os.mkdir('%s/%s' %(authorName,novelName))
            print("%s 資料夾創建成功\n" %novelName) 
    else:
        os.mkdir(authorName)
        print("\n%s 資料夾創建成功\n" %authorName)
        if os.path.exists('%s/%s' %(authorName,novelName)):
            print("%s 資料夾已存在，開始下一步\n" %novelName)
        else:
            os.mkdir('%s/%s' %(authorName,novelName))
            print("%s 資料夾創建成功\n" %novelName) 
        

    

if __name__ == '__main__':
    print("\n範例：https://www.popo.tw/books/197688 。")
    url = input('請輸入小說網址：')
    
    get_articles(url)