# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import os
import re

headers={'Referer': 'http://www.kuaikanmanhua.com/',
         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.139 Safari/537.36',}

s=requests.session()
s.headers=headers

#基本设置
#保存根路径,默认在当前目录下
basepath='./'
#漫画集的首页,示例见下面的网址
url='https://www.kuaikanmanhua.com/web/topic/2322/'

def savejpg(url,path):
    global s
    filename=re.search('.*/(.*\.jpg)',url)[1]
    res=s.get(url)
    #res=requests(url,headers=headers)
    if res.status_code==200:
        print('保存图片'+filename+'到'+path)
        with open(path+filename,'wb') as f:
            f.write(res.content)
            f.close()

def get_imgs(url,path):
    global s
    html=s.get(url).text
    soup=BeautifulSoup(html,'html.parser')
    img_links=soup.select('.kklazy')
    for img_link in img_links:
        savejpg(img_link['data-kksrc'],path)


def parser_index(url):
    comic_img_info={}
    soup=BeautifulSoup(s.get(url).text,'html.parser')
    comic_name=soup.select('.comic-name')[0].text
    comic_titles=soup.findAll('a',attrs={'class':' article-img'})
    for titles in comic_titles:
        comic_img_info['name']=comic_name
        comic_img_info['title']=titles['title']
        comic_img_info['url']='http://www.kuaikanmanhua.com/'+titles['href']
        yield comic_img_info

def main(url=url,basepath=basepath):
    for item in parser_index(url):
        path=basepath+item['name']+'/'+item['title']+'/'
        if not os.path.exists(path):os.makedirs(path)
        get_imgs(item['url'],path)

if __name__=='__main()__':
    main()