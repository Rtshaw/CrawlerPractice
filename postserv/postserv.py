# -*- coding: utf-8 -*-
# 未完成

import re
# import cv2
import requests
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup

s = requests.Session()

# internationalUrl = 'http://postserv.post.gov.tw/pstmail/assets/txn/EB500200/EB500200.html?15t'
internationalUrl = 'http://postserv.post.gov.tw/pstmail/EsoafDispatcher'
uuidUrl = 'http://postserv.post.gov.tw/pstmail/jcaptcha?uuid=83a2f052-626c-4791-bda4-4a1950f1e546'
unknowUrl = 'http://postserv.post.gov.tw/pstmail/assets/txn/EB500200/EB500200.js'


def search():
    url = 'http://postserv.post.gov.tw/pstmail/assets/txn/EB500200/EB500200.html?s6qh'
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }

    s.headers.clear()
    s.headers.update(headers)
    # r = s.post(url, data=data)
    r = s.get(url)
    # 因為爬下來的編碼格式為 ISO-8859-1 所以先編碼後解碼
    # print(r.encoding)
    r = r.text.encode('ISO-8859-1').decode('utf8')
    print(r)


def get_captcha(packageNum):
    url = uuidUrl
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

    # img = cv2.imread('jcaptcha.jpg')

    packageNumber = packageNum
    captcha = input('圖形驗證碼：')

    start_international_search(packageNumber, captcha)
    # clear_noise = cv2.fastNlMeansDenoisingColored(img, None, 35, 10, 7, 21)
    # ret, thresh = cv2.threshold(clear_noise, 30, 255, cv2.THRESH_BINARY_INV)
    # gray = cv2.cvtColor(~thresh, cv2.COLOR_BGR2GRAY)
    # binary = cv2.adaptiveThreshold(
    #     ~gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 9, -10)

    # rows, cols = binary.shape
    # scale = 20
    # #识别横线
    # print(cols)
    # kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (cols//scale,1))
    # eroded = cv2.erode(binary, kernel, iterations = 1)
    # cv2.imshow("Eroded Image",eroded)
    # dilatedcol = cv2.dilate(eroded, kernel, iterations = 1)
    # cv2.imshow("Dilated Image", dilatedcol)

    # #识别竖线
    # print(rows)
    # kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, cols//(scale)))
    # eroded = cv2.erode(binary, kernel, iterations = 1)
    # dilatedrow = cv2.dilate(eroded, kernel, iterations = 1)
    # cv2.imshow("Dilated Image", dilatedrow)

    # # #标识交点
    # bitwiseAnd = cv2.bitwise_and(dilatedcol, dilatedrow)
    # # cv2.imshow("bitwiseAnd Image", bitwiseAnd)

    # # 标识表格
    # merge = cv2.add(dilatedcol, dilatedrow)
    # # cv2.imshow("add Image", merge)

    # cv2.imshow("jcaptcha", binary)
    # cv2.waitKey(0)


def start_international_search(packageNumber, captcha):
    url = internationalUrl
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    data = {
        'body': {
            'MAILNO': packageNumber,
            'captcha': captcha,
            'pageCount': '10',
            'uuid': '83a2f052-626c-4791-bda4-4a1950f1e546',
        },
        'header': {
            'BizCode': 'query',
            'ClientTransaction': 'True',
            'CustID': '',
            'DevMode': 'False',
            'InputVOClass': 'com.systex.jbranch.app.server.post.vo.EB500200InputVO',
            'REQUEST_ID': '',
            'SectionID': 'esoaf',
            'StampTime': 'True',
            'SupvID': '',
            'SupvPwd': '',
            'TXN_DATA': {},
            'TxnCode': '',
        }
    }

    r = s.post(url, data, headers)
    print(r.text)


# body: {MAILNO: "CL043765085JP", uuid: "9d3daa73-59cf-40f2-9716-bc642a803827",
#        captcha: "3698", pageCount: 10}
# MAILNO: "CL043765085JP"
# captcha: "3698"
# pageCount: 10
# uuid: "9d3daa73-59cf-40f2-9716-bc642a803827"
if __name__ == '__main__':
    packageNumber = input('郵件號碼：')
    get_captcha(packageNumber)
    # captcha = input('圖形驗證碼：')
    # start_international_search(packageNumber, captcha)
    # search()
