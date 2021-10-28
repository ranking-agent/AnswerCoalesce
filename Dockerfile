# base this container on python 3.8
FROM python:3.8.5

# get some credit
LABEL maintainer="powen@renci.org"

# update the container
RUN apt-get update

# make a directory for the repo
RUN mkdir /repo

# go to the directory where we are going to upload the repo
WORKDIR /repo

# get the latest code
RUN git clone https://github.com/ranking-agent/AnswerCoalesce.git

# go to the repo dir
WORKDIR /repo/AnswerCoalesce

# install all required packages
RUN pip install -r requirements.txt

RUN pip install uvicorn

# expose the default port
EXPOSE 6380

# start the service entry point
ENTRYPOINT ["bash", "main.sh"]
