FROM python:3.13-slim

# 预装网页抓取和常用分析依赖，避免每次创建沙箱重复安装。
RUN python -m pip install --no-cache-dir beautifulsoup4 markdownify pyyaml pandas plotly