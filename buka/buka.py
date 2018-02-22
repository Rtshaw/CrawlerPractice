# -*- coding: utf-8 -*-

import requests
import time
import os
from bs4 import BeautifulSoup
from lxml import etree

def get_comic(url):
    r = requests.get(url)
    
    try:
        html = etree.HTML(r.content)
        # 章節 待寫 尚未完成
        chapter = html.xpath('//div[@class="manga-episodes"]/select/option/@title')
        # for chap in chapter:
            #p rint(chap)           
        # 標題
        title = html.xpath('//head/title/text()')[0]
        # 建立標題資料夾
        if not os.path.exists('./%s' % title):
            os.mkdir('./%s' % title)
            print('\n創建 "%s" 資料夾完成，進行下一步\n' % title)
        else:
            print('"%s" 資料夾已存在，進行下一步\n' % title)
        # print(title)
        # 圖片網址
        imgone = html.xpath('//div[@class="manga-c"]/img/@src')[0]
        img_r = requests.get(imgone)
        time.sleep(1)
        with open('./%s/0.jpg' % title, mode='wb') as fp:
            fp.write(img_r.content)
        print('0.jpg, ...OK')
        img_url = html.xpath('//div[@class="manga-c"]/img/@data-original')
        # print(tags)
        for index, imgurl in enumerate(img_url, 1):
            img_r = requests.get(imgurl)
            time.sleep(1)
            
            with open('./%s/%s.jpg' % (title, index), mode='wb') as fp:
                fp.write(img_r.content)
            print('%s.jpg, ...OK' % index)
        
        
    except Exception as e:
        raise e
        
if __name__ == '__main__':
    
    print('布卡漫畫下載\n作者：rtshaw\n')
    
    get_comic(input('\n請輸入漫畫網址:'))
    print('\n任務已完成')
    input('按任意鍵退出')