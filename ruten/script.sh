#!/bin/sh

cd /home/ec2-user/CrawlerPractice/ruten
yesterday=$(date -d '-1 day' '+%Y%m%d')
today=$(date '+%Y%m%d')
now=$(date '+%H%M')

if [ -d "./$yesterday" ]
then
	rm -r $(date -d '-1 day' '+%Y%m%d')

fi

if [ ! -d "./$today" ]
then
	mkdir $(date '+%Y%m%d')
fi



source venv/bin/activate

python fee.py > ./"$today"/"$now".txt
