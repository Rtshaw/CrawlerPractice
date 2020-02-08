# -*- coding: utf-8 -*-
import re
import json
import requests
from bs4 import BeautifulSoup

session = requests.Session()
search_url = 'https://www.t-cat.com.tw/Inquire/International.aspx'

def search():
    url = search_url
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    session.headers.clear()
    session.headers.update(headers)
    # r = s.post(url, data=data)
    response = session.get(url)
    # print(r.text)
    soup = BeautifulSoup(response.text, 'lxml')
    viewState = soup.find('input', {'id': '__VIEWSTATE'}).get('value')
    eventValidation = soup.find(
        'input', {'id': '__EVENTVALIDATION'}).get('value')

    return viewState, eventValidation


def start_serch(_viewState, _eventValidation, _packageNnumber):
    url = search_url
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }

    data = {
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$btnQuery',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': _viewState,
        '__VIEWSTATEGENERATOR': '0FD02B3E',
        '__EVENTVALIDATION': _eventValidation,
        'q': '站內搜尋',
        'ctl00$ContentPlaceHolder1$txtReqNo': _packageNnumber,
    }

    session.headers.clear()
    session.headers.update(headers)
    # r = s.get(url)
    response = session.post(url, data, headers)
    # print(r.text)
    soup = BeautifulSoup(response.text, 'lxml')

    table = soup.find('table', {'class': 'tablelist'},
                      id='ContentPlaceHolder1_resultTable')
    # print(table)
    # columns = table.find('tr').find_all('td')
    columns = [td.text.replace('\n', '')
               for td in table.find('tr').find_all('td')]
    trs = table.find_all('tr')[1:]
    rows = list()
    for tr in trs:
        rows.append([td.text.replace('\n', '').replace('\xa0', '')
                     for td in tr.find_all('td')])
    rows[:5]
    json_file = {}

    for c, r in zip(columns, rows[0]):
        json_file.update({c: r})
    
    return json_file
    # print(json_file)
    # with open('./information.json', 'w', encoding='utf-8') as f:
    #     f.write(json.dumps(json_file, ensure_ascii=False))
    #     print('已寫入 json檔')


if __name__ == '__main__':
    viewState, eventValidation = search()
    packageNnumber = input('國際宅急便貨物追蹤號碼：')
    result = start_serch(viewState, eventValidation, packageNnumber)

    if result['國際宅急便包裹查詢號碼'] == f'{packageNnumber}':
        print(result['貨態'])
    else:
        print('目前尚無料資料')
