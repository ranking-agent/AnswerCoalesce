# leverage the renci python base image
FROM ghcr.io/translatorsri/renci-python-image:3.12.4

#Build from this branch.  Assume master for this repo
ARG BRANCH_NAME=master

# update the container
RUN apt-get update

# make a directory for the repo
RUN mkdir /repo

# go to the directory where we are going to upload the repo
WORKDIR /repo

# get the latest code
RUN git clone --branch $BRANCH_NAME --single-branch https://github.com/ranking-agent/AnswerCoalesce.git

# go to the repo dir
WORKDIR /repo/AnswerCoalesce

RUN chmod 777 -R .

# install all required packages
RUN pip install -r requirements.txt

RUN pip install uvicorn

# switch to the non-root user (nru). defined in the base image
USER nru

# expose the default port
EXPOSE 6380

# start the service entry point
ENTRYPOINT ["bash", "main.sh"]
