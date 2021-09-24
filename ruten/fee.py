# -*- coding: utf-8 -*-

__author__ = 'blacktea'
__date__ = '2021/06/13'
__version__ = '0.0.1'

import os
import configparser

# selenium-part
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

print(os.path)
class Ruten():
  def __init__(self):
    self.chrome_options = Options()
    self.chrome_options.add_argument('--no-sandbox')
    self.chrome_options.add_argument('--disable-dev-shm-usage')
    self.chrome_options.add_argument('--headless')

    # self.driver = webdriver.Chrome(ChromeDriverManager().install()) # GUI
    self.driver = webdriver.Chrome(ChromeDriverManager().install(), chrome_options=self.chrome_options)  # no GUI

    # config 設定
    self.config = configparser.ConfigParser()
    self.config.read('config.ini')

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

  def login(self, driver):
    """ 登入露天 """
    try:
      username_locator = (By.XPATH, '//input[@name="userid"]')
      self.webdriver_wait_send_keys(driver, username_locator, self.config['Ruten']['username'])

      password_locator = (By.XPATH, '//input[@name="userpass"]')
      self.webdriver_wait_send_keys(driver, password_locator, self.config['Ruten']['password'])

      login_button_locator = (By.XPATH, '//input[@id="btnLogin"]')
      self.webdriver_click(driver, login_button_locator)
    except Exception as e:
      print(f'login error: {e}')
    
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
      driver.get('https://point.ruten.com.tw/account/fee.php')
      unpaid_dollar = driver.find_element_by_xpath('//div[@class="fee-unit fee-unit-total"]//div[@class="fee-dollar"]').text
      unpaid_dollar = int(unpaid_dollar.split(' ')[0])

      if unpaid_dollar < 10:
        self.card_type = 'VISA'
      elif unpaid_dollar > 100:
        self.card_type = 'JCB'
      else:
        self.card_type = 'MASTER'

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
        self.quit_driver()
        exit()

      crd_rocid = (By.XPATH, '//input[@id="crd_rocid"]') # 身份證
      crd_by = (By.XPATH, '//input[@id="crd_by"]') # 生日年
      crd_bm = (By.XPATH, '//input[@id="crd_bm"]') # 生日月
      crd_bd = (By.XPATH, '//input[@id="crd_bd"]') # 生日日

      crd_n1 = (By.XPATH, '//input[@id="crd_n1"]') # 信用卡1
      crd_n2 = (By.XPATH, '//input[@id="crd_n2"]') # 信用卡2
      crd_n3 = (By.XPATH, '//input[@id="crd_n3"]') # 信用卡3
      crd_n4 = (By.XPATH, '//input[@id="crd_n4"]') # 信用卡4
      crd_l3 = (By.XPATH, '//input[@id="crd_l3"]') # 信用卡安全碼

      invoice_type_locator = (By.XPATH, '//input[@data-option="personal"]') # 發票類型
      pay_button_locator = (By.XPATH, '//button[@class="rt-button rt-button-submit rt-button-large"]') # 送出按鈕
      

      self.webdriver_wait_send_keys(driver, crd_rocid, self.config['Ruten']['userid'])

      self.webdriver_wait_send_keys(driver, crd_by, self.config['Ruten']['birth_year'])
      self.webdriver_wait_send_keys(driver, crd_bm, self.config['Ruten']['birth_month'])
      self.webdriver_wait_send_keys(driver, crd_bd, self.config['Ruten']['birth_day'])

      # 信用卡發行商
      crd_type_element = driver.find_element_by_id('crd_type')

      for option in crd_type_element.find_elements_by_tag_name('option'):
        if option.text == self.card_type:
          option.click()
          break

      self.webdriver_wait_send_keys(driver, crd_n1, self.config[f'{self.card_type}']['card_n1'])
      self.webdriver_wait_send_keys(driver, crd_n2, self.config[f'{self.card_type}']['card_n2'])
      self.webdriver_wait_send_keys(driver, crd_n3, self.config[f'{self.card_type}']['card_n3'])
      self.webdriver_wait_send_keys(driver, crd_n4, self.config[f'{self.card_type}']['card_n4'])
      self.webdriver_wait_send_keys(driver, crd_l3, self.config[f'{self.card_type}']['card_safe'])
      
      crd_dlm_element = driver.find_element_by_id('crd_dlm')
      for option in crd_dlm_element.find_elements_by_tag_name('option'):
        if option.text == self.config[f'{self.card_type}']['card_dlm']:
          option.click()
          break

      crd_dly_element = driver.find_element_by_id('crd_dly')
      for option in crd_dly_element.find_elements_by_tag_name('option'):
        if option.text == self.config[f'{self.card_type}']['card_dly']:
          option.click()
          break

      self.webdriver_click(driver, invoice_type_locator)
      self.webdriver_click(driver, pay_button_locator)
      self.quit_driver()

    except Exception as e:
      print(f'payfee error: {e}')

  def main(self):
    url = 'https://member.ruten.com.tw/user/login.htm'
    driver = self.driver
    driver.get(url)

    self.login(driver)
    self.go_to_fee_center(driver)
    self.payfee(driver)
    
if __name__ == "__main__":
  ruten = Ruten()
  ruten.main()