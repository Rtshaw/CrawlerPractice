import requests
from bs4 import BeautifulSoup

class Animate():
    def __init__(self):
        self.session = requests.Session()
        self.prev_url = 'https://www.animate-onlineshop.jp'
    
    def search(self, smt):
        url = 'https://www.animate-onlineshop.jp/products/list.php'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.190 Safari/537.36'
        }
        params = {
            'sci': '0',
            'smt': smt,
            'ss': '1',
            'sl': '20',
            'nf': '1',
            'spc': '',
            'scc': '',
            'ssy': '',
            'ssm': '',
            'sey': '',
            'sem': '',
            'nd[]': '7',
        }
        response = self.session.get(url, headers=headers, params=params)
        soup = BeautifulSoup(response.text, 'lxml')
        items = soup.find('div', class_='item_list')
        items_title = []
        items_url = []
        # items_title = [item.find('a')['title'] for item in items.find_all('h3')]
        for item in items.find_all('div', class_='item_list_thumb'):
            img_tag = item.find('img')
            a_tag = item.find('a')
            items_title.append(img_tag['title'])
            items_url.append(self.prev_url + a_tag['href'])
        
        print(items_title)
        print(items_url)

if __name__ == "__main__":
    animate = Animate()
    # smt = input('關鍵字：')
    animate.search(smt)
