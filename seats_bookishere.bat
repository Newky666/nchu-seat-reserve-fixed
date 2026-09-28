@echo off
chcp 65001 >nul
title 昌航图书馆座位预约
setlocal

rem 优先用窗口版 pyw(无黑色控制台), 找不到就退回 py
set "PY=pyw"
where pyw >nul 2>nul || set "PY=py"

start "" "%PY%" "%~dp0gui.py"
