# -*- coding: utf-8 -*-
import re
import json
import requests
from bs4 import BeautifulSoup


s = requests.Session()
search_url = 'https://www.t-cat.com.tw/Inquire/International.aspx'


def search():
		url = search_url
		headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
		s.headers.clear()
		s.headers.update(headers)
    # r = s.post(url, data=data)
		r = s.get(url)
		# print(r.text)
		soup = BeautifulSoup(r.text, 'lxml')
		vs = soup.find('input', {'id':'__VIEWSTATE'}).get('value')
		ev = soup.find('input', {'id':'__EVENTVALIDATION'}).get('value')

		return vs, ev

def start_serch(viewstate, eventvalidation, package_number):
    url = search_url
    headers = {
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }

    data = {
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$btnQuery',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': viewstate,
        '__VIEWSTATEGENERATOR': '0FD02B3E',
        '__EVENTVALIDATION': eventvalidation,
        'q': '站內搜尋',
        'ctl00$ContentPlaceHolder1$txtReqNo': package_number,
    }

    s.headers.clear()
    s.headers.update(headers)
    # r = s.get(url)
    r = s.post(url, data, headers)
    # print(r.text)
    soup = BeautifulSoup(r.text, 'lxml')

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
    # print(trs)
    # print(rows)
    # print(columns)
    json_file = {}
    for c, r in zip(columns, rows[0]):
        json_file.update({c: r})
    # print(json_file)
    with open('./information.json', 'w', encoding='utf-8') as f:
        f.write(json.dumps(json_file, ensure_ascii=False))
        print('已寫入 json檔')


if __name__ == '__main__':
	viewstate, eventvalidation = search()
	package_number = input('國際宅急便貨物追蹤號碼：')
	start_serch(viewstate, eventvalidation, package_number)
