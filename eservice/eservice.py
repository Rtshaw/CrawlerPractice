# -*- coding: utf-8 -*-

__author__ = 'rtshaw'
__date__ = '2020/02/13'
__version__ = '0.0.1'

import os
import re
import lxml
import json
import requests
from bs4 import BeautifulSoup

import solve_captchas

session = requests.Session()

best_model = os.getcwd() + '/best_model.hdf5'
model_labels = os.getcwd() + '/model_labels.dat'


def search(tracking_number):
    # get search page
    url = 'https://eservice.7-11.com.tw/e-tracking/search.aspx'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    response = session.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'lxml')

    __VIEWSTATE = soup.find('input', {'id': '__VIEWSTATE'}).get('value')
    __VIEWSTATEGENERATOR = soup.find(
        'input', {'id': '__VIEWSTATEGENERATOR'}).get('value')

    check_code_url = soup.find(id='ImgVCode')['src']
    check_code_url = 'https://eservice.7-11.com.tw/e-tracking/' + check_code_url

    get_check_code(check_code_url)

    # start search
    # data = {
    #     '__LASTFOCUS': '',
    #     '__EVENTTARGET': '',
    #     '__EVENTARGUMENT': '',
    #     '__VIEWSTATE': __VIEWSTATE,
    #     '__VIEWSTATEGENERATOR': __VIEWSTATEGENERATOR,
    #     'txtProductNum': tracking_number,
    #     'tbChkCode': check_code,
    #     'aaa': '',
    #     'txtIMGName': '',
    #     'txtPage': '1',
    # }
    # response = session.post(url, headesr=headers, data=data)
    # print(response.text)


def get_check_code(check_code_url):
    url = check_code_url
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    response = session.get(url, headers=headers)
    with open('captcha.jpg', 'wb') as w:
        w.write(response.content)

    captcha = solve_captchas.solve_captcha_with_models(
        os.getcwd()+'/captcha.jpg', best_model, model_labels)

    print(captcha)


# def start_search(viewstate, productNumber, captcha):
#     url = searchUrl
#     headers = {
#         'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
#     }
#     data = {
#         '__EVENTTARGET': 'submit',
#         '__EVENTARGUMENT': '',
#         '__VIEWSTATE': viewstate,
#         '__VIEWSTATEGENERATOR': '3E7313DB',
#         'txtProductNum': productNumber,
#         'tbChkCode': captcha,
#         'aaa': '',
#         'txtIMGName': '',
#         'txtPage': '1',
#     }
#     r = s.post(url, data, headers)
#     # 因為爬下來的編碼格式為 ISO-8859-1 所以先編碼後解碼
#     # print(r.encoding)
#     # r = r.text.encode('ISO-8859-1').decode('utf8')
#     # print(r.text)

#     soup = BeautifulSoup(r.text, 'lxml')
#     # status = soup.select('div.m_news')

#     webTitle = soup.title.contents[0]  # E-Tracking 貨態查詢系統
#     # print(webTitle)

#     if(webTitle == 'E-Tracking 貨態查詢系統'):
#         status = soup.find('div', id='last_message').contents[0]  # 已完成包裹成功取件
#         # 2019/05/27 15:46:00
#         statusTime = soup.find('div', id='last_message').contents[2]
#         # print(status)
#         # print(statusTime)

#         searchCode = soup.find('h2').contents[0]  # 查詢代碼：
#         productNum = soup.find(
#             'span', id='query_no').contents[0]  # G32737408719
#         # print(searchCode)
#         # print(productNum)

#         productInfo = soup.find(
#             'label', id='StatusInfo_Title').contents[1]  # 取貨資訊
#         # print(productInfo)

#         storeNameTitle = soup.find(
#             'h4', id='store_name_Title').contents[0]  # 取貨門市
#         storeName = soup.find('span', id='store_name').contents[0]  # 狀元
#         # print(storeNameTitle, storeName)

#         storeAddressTitle = soup.find(
#             'h4', id='store_address_Title').contents[0]  # 取貨門市地址
#         storeAddress = soup.find(
#             'p', id='store_address').contents[0]  # 南投縣竹山鎮大明路500號
#         # print(storeAddressTitle, storeAddress)

#         deadlineTitle = soup.find(
#             'h4', id='deadline_Title').contents[0]  # 取貨截止日
#         deadline = soup.find('span', id='deadline').contents[0]  # 2019-06-01
#         # print(deadlineTitle, deadline)

#         serviceType = soup.find('h4', id='servicetype').contents[0]  # 取貨付款
#         # print(serviceType)

#         jsonFile = {
#             'status': status,
#             'status_time': statusTime,
#             'search_code': searchCode,
#             'product_number': productNum,
#             'product_info': productInfo,
#             'store_name_title': storeNameTitle,
#             'store_name': storeName,
#             'store_address_title': storeAddressTitle,
#             'store_address': storeAddress,
#             'deadline_title': deadlineTitle,
#             'deadline': deadline,
#             'service_type': serviceType,
#         }

#         with open('./information.json', 'w', encoding='utf-8') as f:
#             f.write(json.dumps(jsonFile, ensure_ascii=False))
#             print('已寫入 json檔')
#     else:
#         print('網頁又掛了~')

if __name__ == '__main__':
    tracking_number = input('查詢代碼 ')
    search(tracking_number)
    # viewstate = search()
    # get_captcha()
    # productNumber = input('取/寄件編碼：')
    # captcha = input('驗證碼：')
    # start_search(viewstate, productNumber, captcha)

# G56852849894
# G32737408719
# E14188201691
