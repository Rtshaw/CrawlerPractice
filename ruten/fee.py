# -*- coding: utf-8 -*-

__author__ = 'blacktea'
__date__ = '2021/06/13'
__version__ = '0.0.1'

import os
import platform
import configparser
import time
import json

# selenium-part
from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc

try:
  from webdriver_manager.chrome import ChromeDriverManager
except:
  pass

class Ruten():
  def __init__(self):
    system = platform.system()
    if system == 'Linux':
      os.system('pkill chrome')
      os.system("kill $(ps aux | grep webdriver| awk '{print $2}')")

    self.chrome_options = webdriver.ChromeOptions()
    self.chrome_options.add_argument('--no-sandbox') # 讓 Chrome在 root權限下執行
    # self.chrome_options.add_argument('--disable-dev-shm-usage')
    self.chrome_options.add_experimental_option("useAutomationExtension", False) # 不顯示 Chrome正受到自動測試軟體控制
    self.chrome_options.add_experimental_option("excludeSwitches", ['enable-automation'])
    self.chrome_options.add_experimental_option("detach", True)
    # self.chrome_options.add_argument('--headless') # 不用打開圖形界面

    # self.driver = webdriver.Chrome(ChromeDriverManager().install()) # no option
    # self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.chrome_options)  # has options
    self.driver = uc.Chrome()
    
    # if system == 'Linux':
    #   self.driver = webdriver.Chrome('/usr/lib/chromium-browser/chromedriver', options=self.chrome_options)

    # config 設定
    self.config = configparser.ConfigParser()
    self.config.read('config.ini', encoding='utf-8')

    self.card_type = 'MASTER'

  def quit_driver(self):
    """ 關閉瀏覽器 """
    self.driver.quit()

  @staticmethod
  def webdriver_wait_send_keys(driver, locator, value):
      WebDriverWait(driver, 10, 5).until(EC.presence_of_element_located(locator)).send_keys(value)

  @staticmethod
  def webdriver_click(driver, locator):
      WebDriverWait(driver, 10, 5).until(EC.presence_of_element_located(locator)).click()


  def close_ad(self, driver):
    """ 關閉露天廣告 """
    try:
      window_close_locator = (By.XPATH, '//button[@class="rt-lightbox-close-button"]')
      self.webdriver_click(driver, window_close_locator)
    except Exception as e:
      print(f'close_ad error: {e}')

  def go_to_fee_center(self, driver):
    """ 前往計費中心 """
    try:
      time.sleep(1)
      driver.get('https://point.ruten.com.tw/account/fee.php')
      # unpaid_dollar = driver.find_element_by_xpath('//div[@class="fee-unit fee-unit-total"]//div[@class="fee-dollar"]').text
      # unpaid_dollar = int(unpaid_dollar.split(' ')[0])

      # if unpaid_dollar < 10:
      #   self.card_type = 'VISA'
      # elif unpaid_dollar > 100:
      #   self.card_type = 'JCB'
      # else:
      #   self.card_type = 'MASTER'

      self.card_type = 'MASTER' # 強制指定卡別

    except Exception as e:
      print(f'go_to_fee_center error: {e}')
  
  def payfee(self, driver):
    """ 繳費 """
    try:
      try:
        credit_card_btn_locator = (By.XPATH, '//button[@id="pay_credit_card"]')
        self.webdriver_click(driver, credit_card_btn_locator)
      except:
        print('[INFO] 目前沒有費用需要繳交')
        # self.quit_driver()
        # exit()

      crd_rocid = (By.XPATH, '//input[@id="crd_rocid"]') # 身份證
      crd_by = (By.XPATH, '//input[@id="crd_by"]') # 生日年
      crd_bm = (By.XPATH, '//input[@id="crd_bm"]') # 生日月
      crd_bd = (By.XPATH, '//input[@id="crd_bd"]') # 生日日

      crd_n1 = (By.XPATH, '//input[@id="crd_n1"]') # 信用卡1
      crd_n2 = (By.XPATH, '//input[@id="crd_n2"]') # 信用卡2
      crd_n3 = (By.XPATH, '//input[@id="crd_n3"]') # 信用卡3
      crd_n4 = (By.XPATH, '//input[@id="crd_n4"]') # 信用卡4
      crd_l3 = (By.XPATH, '//input[@id="crd_l3"]') # 信用卡安全碼
      
      zipcode = (By.XPATH, '//input[@id="zipcode"]') # 3碼郵遞區號
      zipcode_accurate = (By.XPATH, '//input[@id="zipcode_accurate"]') # 2碼郵遞區號

      invoice_type_locator = (By.XPATH, '//input[@data-option="personal"]') # 發票類型
      pay_button_locator = (By.XPATH, '//button[@class="rt-button rt-button-submit rt-button-large"]') # 送出按鈕
      
      time.sleep(1)
      self.webdriver_wait_send_keys(driver, crd_rocid, self.config['Ruten']['userid'])

      self.webdriver_wait_send_keys(driver, crd_by, self.config['Ruten']['birth_year'])
      self.webdriver_wait_send_keys(driver, crd_bm, self.config['Ruten']['birth_month'])
      self.webdriver_wait_send_keys(driver, crd_bd, self.config['Ruten']['birth_day'])

      self.webdriver_wait_send_keys(driver, crd_n1, self.config[f'{self.card_type}']['card_n1'])
      self.webdriver_wait_send_keys(driver, crd_n2, self.config[f'{self.card_type}']['card_n2'])
      self.webdriver_wait_send_keys(driver, crd_n3, self.config[f'{self.card_type}']['card_n3'])
      self.webdriver_wait_send_keys(driver, crd_n4, self.config[f'{self.card_type}']['card_n4'])
      self.webdriver_wait_send_keys(driver, crd_l3, self.config[f'{self.card_type}']['card_safe'])

      self.webdriver_wait_send_keys(driver, zipcode, self.config['Ruten']['zipcode'])
      self.webdriver_wait_send_keys(driver, zipcode_accurate, self.config['Ruten']['zipcode_accurate'])
      
      crd_dlm_select = Select(driver.find_element(By.XPATH, '//select[@id="crd_dlm"]'))
      crd_dlm_select.select_by_value(self.config[self.card_type]['card_dlm'])
      
      crd_dly_select = Select(driver.find_element(By.XPATH, '//select[@id="crd_dly"]'))
      crd_dly_select.select_by_value(self.config[self.card_type]['card_dly'])

      self.webdriver_click(driver, invoice_type_locator)
      time.sleep(1)
      self.webdriver_click(driver, pay_button_locator)
      # self.quit_driver()

    except Exception as e:
      print(f'payfee error: {e}')
    
  def get_sms(self, driver):
    """ 取得簡訊 """
    sms_button_locator = (By.XPATH, '//button[@class="btn btn-block btn-primary mb-2"]')
    self.webdriver_click(driver, sms_button_locator)

    time.sleep(50)
    

  def main(self):
    url = 'https://member.ruten.com.tw/user/login.htm'
    driver = self.driver
    
    driver.get(url)
    with open('cookies.json') as f:
        cookies = json.load(f)
    
    for cookie in cookies:
        # print(cookie)
        if 'sameSite' in cookie:
          if cookie['sameSite'] == 'unspecified':
            cookie['sameSite'] = 'Strict'
          if cookie['sameSite'] == 'no_restriction':
            cookie['sameSite'] = 'Strict'
        driver.add_cookie(cookie)
    driver.refresh()

    driver.set_window_size(1200, 600)
    driver.get(url)

    self.go_to_fee_center(driver)
    self.payfee(driver)
    self.get_sms(driver)
    
if __name__ == "__main__":
  ruten = Ruten()
  ruten.main()