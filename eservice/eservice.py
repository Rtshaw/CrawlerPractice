# -*- coding: utf-8 -*-
# dolist:驗證碼影像辨識

import re
import lxml
import json
import requests
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup

s = requests.Session()

searchUrl = 'https://eservice.7-11.com.tw/E-Tracking/search.aspx'
imgVCode = 'https://eservice.7-11.com.tw/E-Tracking/ValidateImage.aspx?ts=1600580604'


def search():
    url = searchUrl
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }

    s.headers.clear()
    s.headers.update(headers)
    # r = s.post(url, data=data)
    r = s.get(url)
    soup = BeautifulSoup(r.text, 'lxml')
    # print(r.text)
    vs = soup.find('input', {'id':'__VIEWSTATE'}).get('value')
    # print(viewstate)
    return vs



def get_captcha():
    url = imgVCode
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    s.headers.clear()
    s.headers.update(headers)
    r = s.get(url)
    # print(r.content)
    with open('jcaptcha.jpg', 'wb') as w:
        w.write(r.content)


def start_search(viewstate, productNumber, captcha):
    url = searchUrl
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    data = {
        '__EVENTTARGET': 'submit',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': viewstate,
        '__VIEWSTATEGENERATOR': '3E7313DB',
        'txtProductNum': productNumber,
        'tbChkCode': captcha,
        'aaa': '',
        'txtIMGName': '',
        'txtPage': '1',
    }
    r = s.post(url, data, headers)
    # 因為爬下來的編碼格式為 ISO-8859-1 所以先編碼後解碼
    # print(r.encoding)
    # r = r.text.encode('ISO-8859-1').decode('utf8')
    # print(r.text)

    soup = BeautifulSoup(r.text, 'lxml')
    # status = soup.select('div.m_news')

    webTitle = soup.title.contents[0] # E-Tracking 貨態查詢系統
    # print(webTitle)

    if(webTitle == 'E-Tracking 貨態查詢系統'):
        status = soup.find('div', id='last_message').contents[0] # 已完成包裹成功取件
        statusTime = soup.find('div', id='last_message').contents[2] # 2019/05/27 15:46:00
        # print(status)
        # print(statusTime)

        searchCode = soup.find('h2').contents[0] # 查詢代碼：
        productNum = soup.find('span', id='query_no').contents[0] # G32737408719
        # print(searchCode)
        # print(productNum)

        productInfo = soup.find('label', id='StatusInfo_Title').contents[1] # 取貨資訊
        # print(productInfo)

        storeNameTitle = soup.find('h4', id='store_name_Title').contents[0] # 取貨門市
        storeName = soup.find('span', id='store_name').contents[0] # 狀元
        # print(storeNameTitle, storeName)

        storeAddressTitle = soup.find('h4', id='store_address_Title').contents[0] # 取貨門市地址
        storeAddress = soup.find('p', id='store_address').contents[0] # 南投縣竹山鎮大明路500號
        # print(storeAddressTitle, storeAddress)

        deadlineTitle = soup.find('h4', id='deadline_Title').contents[0] # 取貨截止日
        deadline = soup.find('span', id='deadline').contents[0] # 2019-06-01
        # print(deadlineTitle, deadline)

        serviceType = soup.find('h4', id='servicetype').contents[0] # 取貨付款
        # print(serviceType)

        jsonFile = {
            'status': status,
            'status_time': statusTime,
            'search_code': searchCode,
            'product_number': productNum,
            'product_info': productInfo,
            'store_name_title': storeNameTitle,
            'store_name': storeName,
            'store_address_title': storeAddressTitle,
            'store_address': storeAddress,
            'deadline_title': deadlineTitle,
            'deadline': deadline,
            'service_type': serviceType,
        }

        with open('./information.json', 'w', encoding='utf-8') as f:
            f.write(json.dumps(jsonFile, ensure_ascii=False))
            print('已寫入 json檔')
    else:
        print('網頁又掛了~')





if __name__ == '__main__':
    viewstate = search()
    get_captcha()
    productNumber = input('取/寄件編碼：')
    captcha = input('驗證碼：')
    start_search(viewstate, productNumber, captcha)
    
# G56852849894
# G32737408719