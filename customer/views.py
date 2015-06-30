# encoding=utf-8

import sys


reload(sys)
sys.setdefaultencoding('utf-8')
__author__ = 'nerve'
from TTEngine import settings
from programBranch import Operation
import paramiko
import stat
import hashlib
import os
import tarfile
import zipfile
from mongoengine import Q
from django.core.paginator import Paginator, InvalidPage, EmptyPage, PageNotAnInteger
from TTEngine.settings import PAGE_SIZE
from compile.modules import CompilingUpdateRecord
from customer.LicenseDataGenerator import LicenseDataGenerator
from module.RunInfoGenerator import getCrontable, genCheckAll, genDailyRestart,win_genDailyRestart
from utils.OsHelper import isWindows, isThisWindows, OS_TYPE_LINUX, OS_TYPE_WINDOWNS
import utils.PathHelper as pathHelper
from utils.StringHelper import replaceStr
from utils.SvnInfo import getSvnInfo
from utils.TarfileHelper import addfilefromstring, addfile
from subprocess import Popen, PIPE
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response, render, get_object_or_404, redirect
from django.template import RequestContext
from django.template.loader import get_template
from django.template import Context
from django.http import HttpResponse
import json
from module.models import Module, FileInfo, Group
from customer.models import *
import datetime
import time
import logging
from utils.decorator import core_logger
from logger.models import CoreLogger
from TTEngine.constants import *
from package.models import Package
from usrmgr.models import User
from TTEngine.settings import ENCODE, HOST_IP,TEMP_ROOT
from module.Timing import *
import re
import traceback
from threading import Lock
from StringIO import StringIO
from utils.decorator import convert_machine_to_json, convert_compiling_record_to_json
from utils.TracebackHelper import getTraceBack
from programBranch.models import BranchInfo, PROGRAM_LIST, getLocalDir,KeySubmit
import types
import pysvn
from xtplatform.PlatformGenerator import genPlatform
from portal.models import PortalPackage,PortalMachine,PortalUpgradeSql
from customer.KeepalivedConfig import *
from customer.MysqlConfig import *
from bson.dbref import DBRef
from utils.svn_utils import SvnUtils
import uuid
import MySQLdb
from customer.onetimestatus import get_serve_status,get_portal_status
from django.core.mail import send_mail

logger = logging.getLogger('django')
deployINFO = ""
compileINFO = ""
deployPercent = 0
record_id = ""
record_type = ""
def tryAddString(path, str, mode=644):
    sha1 = hashlib.sha1(str).hexdigest()
    size = len(str)
    details = FileInfoDetail.objects(filePath=path, sha1=sha1, size=size)
    detail = None
    if len(details) > 0:
        detail = details[0]
    else:
        detail = FileInfoDetail()
        detail.filePath = path
        detail.info = FileInfo()
        detail.info.filePath = path
        detail.info.rawPath = ""
        detail.info.mod = mode
        detail.info.fileType = FILE_TYPE_UNKNOWN
        detail.info.descript = ""
        detail.info.remark = "产生的文件"
        detail.info.createTime = datetime.datetime.now()
        detail.info.updateTime = datetime.datetime.now()
        detail.info.save()
        detail.sha1 = hashlib.sha1(str).hexdigest()
        detail.size = len(str)
        detail.svnVersion = ""
        stingIo = StringIO(str)
        detail.file.put(stingIo)
        detail.createTime = datetime.datetime.now()
        detail.updateTime = datetime.datetime.now()
    return detail


def tryAddFile(path, rawPath, mode=644):
    fStat = os.stat(rawPath)
    f = open(rawPath)
    content = f.read()
    return tryAddString(path, content, mode)

def get_mail_message(record):
    response = {'success':False, 'error':''}
    customer = record.customer
    check_record = CustomerDeployCheckRecord.objects(customer=customer).order_by("-start_time")
    if len(check_record) > 0:
        check_record = check_record[0]
    is_checked = record.is_checked
    if is_checked == '' or is_checked is None or is_checked == '否':
        mail_message = "客户[%s]尚未进行升级检查,请尽快进行升级检查并填写升级检查记录!  \n" %str(customer.name)
        mail_message += '======================================================================= \n'
        mail_message += '客户:                        %s\n' %str(record.customer.name)
        if len(record.cus_package.machine_packages) == 1:
            mail_message += '版本号:                     %s\n' %str(record.cus_package.machine_packages[0].version)
            mail_message += '机器:                       %s\n' %str(record.cus_package.machine_packages[0].machine.name)
        elif len(record.cus_package.machine_packages) == 2:
            mail_message += '版本号:                     %s\n %s\n' %str(record.cus_package.machine_packages[0].version, record.cus_package.machine_packages[1].version)
            mail_message += '机器:                       %s\n %s\n' %str(record.cus_package.machine_packages[0].machine.name, record.cus_package.machine_packages[1].machine.name)
        mail_message += 'Portal:                     %s\n' %str(record.cus_package.portal_package.svn_version)
        mail_message += '开始时间:                  %s\n' %str(record.start_time)
        mail_message += '结束时间:                  %s\n' %str(record.end_time)
        mail_message += '升级实施人员:            %s\n' %str(record.deploy_user)
        mail_message += '升级备注:                  %s\n' %str(record.remark)
        mail_message += '是否升级检查:              %s\n' %str(record.is_checked )
        mail_message += '升级检查人员:            %s\n' %str(record.check_user)
        mail_message += '录入时间:                 %s\n' %str(record.create_time)
        mail_message += '录入人员:                 %s\n' %str(record.create_user)
        mail_message += '======================================================================= \r\n'
        return mail_message
    else:
        if len(check_record) > 0:
            mail_message = "升级记录  \n"
            mail_message += '======================================================================= \n'
            mail_message += '客户:                        %s\n' %str(record.customer.name)
            if len(record.cus_package.machine_packages) == 1:
                mail_message += '版本号:                     %s\n' %str(record.cus_package.machine_packages[0].version)
                mail_message += '机器:                       %s\n' %str(record.cus_package.machine_packages[0].machine.name)
            elif len(record.cus_package.machine_packages) == 2:
                mail_message += '版本号:                     %s\n %s\n' %str(record.cus_package.machine_packages[0].version, record.cus_package.machine_packages[1].version)
                mail_message += '机器:                       %s\n %s\n' %str(record.cus_package.machine_packages[0].machine.name, record.cus_package.machine_packages[1].machine.name)
            mail_message += 'Portal:                     %s\n' %str(record.cus_package.portal_package.svn_version)
            mail_message += '开始时间:                  %s\n' %str(record.start_time)
            mail_message += '结束时间:                  %s\n' %str(record.end_time)
            mail_message += '升级实施人员:            %s\n' %str(record.deploy_user)
            mail_message += '升级备注:                  %s\n' %str(record.remark)
            mail_message += '是否升级检查:              %s\n' %str(record.is_checked )
            mail_message += '升级检查人员:            %s\n' %str(record.check_user)
            mail_message += '录入时间:                 %s\n' %str(record.create_time)
            mail_message += '录入人员:                 %s\n' %str(record.create_user)
            mail_message += '======================================================================= \r\n'
            mail_message += '升级检查记录  \n'
            mail_message += '======================================================================= \n'
            mail_message += '开始时间:                  %s\n' %str(check_record.start_time)
            mail_message += '结束时间:                  %s\n' %str(check_record.end_time)
            mail_message += '升级检查人员:            %s\n' %str(check_record.check_user)
            mail_message += '升级检查备注:            %s\n' %str(check_record.remark)
            mail_message += '录入时间:                 %s\n' %str(check_record.create_time)
            mail_message += '录入人员:                 %s\n' %str(check_record.create_user)
            mail_message += '======================================================================= \n'
            return mail_message
        else:
            mail_message = ""
            return mail_message

def get_update_check_Xt(ssh, num):
     stdin, stdout, stderr = ssh.exec_command('ps aux |grep Xt')
     lines = stdout.readlines()
     length = len(lines)
     is_success = False
     if length >= num+2:
         is_success = True
     else:
         is_success = False
     return is_success

def get_update_check_Nginx(ssh):
     stdin, stdout, stderr = ssh.exec_command('ps aux |grep nginx')
     lines = stdout.readlines()
     count =0
     is_success = False
     for stdline in lines:
         if "master process" in stdline or "worker process" in stdline:
               count = count + 1
     if count != 4:
         is_success = False
     else:
         is_success = True
     return is_success

def get_update_check_Python(ssh):
     stdin, stdout, stderr = ssh.exec_command('ps aux |grep python')
     lines = stdout.readlines()
     length = len(lines)
     is_success = False
     if length >= 8:
         is_success = True
     else:
         is_success = True
     return is_success

def get_update_check_Lua(ssh,num):
     stdin, stdout, stderr = ssh.exec_command('ps aux |grep lua')
     lines = stdout.readlines()
     is_success = False
     length = len(lines)
     count = 0
     if length >= num+2:
         for stdline in lines:
             if  "checkorder.lua" in stdline or "checkposition.lua" in stdline:
                   count = count + 1
         if count != 2:
             is_success = False
         else:
            is_success = True
     else:
         is_success = False
     return is_success

def get_nginx_xtserver(ssh):
    stdin,stdout,stderr = ssh.exec_command('ps aux| grep Xt')
    server_flag = False
    is_success = False
    for line in stdout.readlines():
        if 'XtService' in line:
            server_flag = True
    if server_flag:
        stdin,stdout,stderr = ssh.exec_command('killall XtService')
        time.sleep(3)
        stdin,stdout,stderr = ssh.exec_command('ps aux| grep Xt')
        for line in stdout.readlines():
            if 'XtService' in line:
                is_success = True
    return is_success

def get_nginx_nginx(ssh):
    is_success = get_update_check_Nginx(ssh)
    nginx_flag = False
    if is_success:
        stdin,stdout,stderr = ssh.exec_command('killall nginx')
        time.sleep(2)
        is_success = get_update_check_Nginx(ssh)
        if is_success:
            nginx_flag = True
    return nginx_flag

def get_update_check_Mysql(host):
     db = MySQLdb.connect(host=host, user='root', passwd='mysql.rzrk')
     cursor = db.cursor()
     sql = 'show slave status'
     cursor.execute(sql)
     data = cursor.fetchall()
     data = data[0]
     io = data[10]
     sql = data[11]
     sql_flag = True
     if io == 'Yes' and sql == 'Yes':
         sql_flag = True
     else:
         sql_flag = False
     return sql_flag

def get_update_check_Keepalived(ssh_master, ssh_slave):
      is_success = get_update_check_Xt(ssh_master)
      flag = False
      if is_success:
          stdin, stdout, stderr = ssh_master.exec_command('ps aux |grep keepalived')
          lines = stdout.readlines()
          length = len(lines)
          if length == 4:
              stdin, stdout, stderr = ssh_master.exec_command('service keepalived restart')
              time.sleep(5)
              stdin, stdout, stderr = ssh_master.exec_command('ps aux |grep keepalived')
              std_lines = stdout.readlines()
              std_len = len(std_lines)
              if std_len <= 2:
                  is_success = get_update_check_Xt(ssh_slave)
                  if is_success:
                      flag = True
                  else:
                      flag = False
      else:
          flag = False

      return flag

# 创建客户
@csrf_exempt
@login_required
def create(request):
    if request.method == "GET":
        path = request.path
        is_sys = None
        if path == '/customer/system/create/':
            is_sys = True
        elif path == '/customer/create/':
            is_sys = False
        else:
            error = "非法请求!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        modules = Module.objects().order_by("+name")
        permissions = CustomerPermissionSettings.objects()
        return render_to_response("customer/customer_create.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        modules = Module.objects()
        response = {"success": False, "error": "", "id": None}
        try:
            # 获取参数
            request_json = json.loads(request.POST.get("json"))
            now = datetime.datetime.now()
            # 校验参数 TODO
            # 保存
            # 先保存机器
            machineList = request_json["machineList"]
            machine_list = []
            for item in machineList:
                machine = None
                machine_id = item["machine_id"]
                if machine_id:
                    machine = Machine.objects(pk=machine_id)[0]
                else:
                    machine = Machine()
                machine.os = item["machine_os"]
                machine.name = item["machine_name"]
                machine.type = item['machine_type']
                machine.code = item["machine_code"]
                machine.host = item["machine_host"]
                machine.port = int(item["machine_port"]) if item["machine_port"] else None
                machine.username = item["machine_username"]
                machine.password = item["machine_password"]
                machine.xtDir = item["machine_xtDir"]
                machine.remark = item["machine_remark"]
                machine_module_list = []
                for module_item in item["modules"]:
                    machine_module_list.append(Module.objects(pk=module_item)[0])
                machine.modules = machine_module_list
                machine.settings = item["settings"]
                if len(machine.settings.strip()) == 0:
                    machine.settings = "{}"
                machine.save()
                machine_list.append(machine)

            # 获取模块列表
            cus_modules_list = []
            for cus_module_item in request_json["moduleList"]:
                cus_modules_list.append(Module.objects(pk=cus_module_item)[0])

            # 权限信息
            permission_dict = {}
            customerPermission = request_json['customerPermission']
            for perm_item in customerPermission:
                perm_id = perm_item['permission_id']
                perm_val = perm_item['permission_value']
                if len(CustomerPermissionSettings.objects(pk=perm_id)) > 0:
                    value = json.loads(perm_val)
                    if isinstance(value, types.BooleanType):
                        if value is True:
                            value = 1
                        else:
                            value = 0
                    permission_dict[perm_id] = value

            # 保存客户信息
            customer_id = request_json["customerId"]
            customer = None
            if customer_id:
                customer = Customer.objects(pk=customer_id)[0]
            else:
                customer = Customer()
            # 客户的默认版本号为当前时间
            customer.version = VERSION_PREFIX_CUSTOMER + str(int(time.time() * 1000))
            customer.name = request_json["customerName"]
            customer.tag = request_json["customerTag"]
            customer.aftersale = request_json["customerAftersale"]
            customer.customerstatus = request_json["customerCustomerstatus"]
            customer.virtual_ip = request_json["customer_virtual_ip"]
            customer.outer_trade_ip = request_json["customer_outer_trade_ip"]
            customer.outer_market_ip = request_json["customer_outer_market_ip"]
            customer.outer_portal_ip = request_json["customer_outer_portal_ip"]
            customer.proxy_ip = request_json["customer_proxy_ip"]
            customer.update_server_ip = request_json["update_server_ip"]
            customer.position = request_json["customer_position"]
            customer.is_sys = request_json["customer_is_sys"]
            customer.permissions = permission_dict
            customer.modules = cus_modules_list
            customer.machines = machine_list
            customer.settings = request_json["settings"]
            if len(customer.settings.strip()) == 0:
                customer.settings = "{}"
            if not customer_id:
                customer.createTime = now
            customer.modifyTime = now
            customer.save()

            response["success"] = True
            response["id"] = str(customer.id)
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception, e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


# 创建客户
@csrf_exempt
@login_required
def edit(request):
    if request.method == "GET":
        try:
            # 初始化模块列表
            modules = Module.objects().order_by("+name")

            # 标记编辑
            is_edit = True
            cus_id = request.GET.get("cus_id", None)
            if cus_id is None:
                error = '编辑用户时ID为空!'
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

            customer = Customer.objects(pk=cus_id)
            if len(customer) == 0:
                error = '编辑用户ID[%s]不存在!' % cus_id
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

            customer = customer[0]
            is_sys = customer.is_sys
            permissions = CustomerPermissionSettings.objects()
            groups = Group.objects()
            cus_permissions = customer.permissions
            return render_to_response("customer/customer_create.html", locals(), context_instance=RequestContext(request))
        except Exception as e:
            error = '编辑用户异常![%s]' % str(e)
            logger.error(error + getTraceBack())
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


# 查看客户
@csrf_exempt
@login_required
def view(request):
    if request.method == "GET":
        try:
            # 初始化模块列表
            modules = Module.objects().order_by("+name")
            # 标记查看
            is_view = True
            cus_id = request.GET.get("cus_id", None)
            if cus_id is None:
                error = '查看用户时ID为空!'
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

            customer = Customer.objects(pk=cus_id)
            if len(customer) == 0:
                error = '查看用户ID[%s]不存在!' % cus_id
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

            groups = Group.objects()
            customer = customer[0]
            return render_to_response("customer/customer_create.html", locals(), context_instance=RequestContext(request))
        except Exception as e:
            error = '查看用户异常![%s]' % str(e)
            logger.error(error + getTraceBack())
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


# 客户列表
@csrf_exempt
@login_required
def cus_list(request):
    path = request.path
    is_sys = None
    if path == '/customer/system/list/':
        is_sys = True
    elif path == '/customer/list/':
        is_sys = False
    else:
        is_sys = False

    customers = Customer.objects(is_sys=is_sys).order_by('+tag')
    customerdeploystatus = CustomerDeployStatus.objects()
    error = request.GET.get("error", None)

    return render_to_response("customer/customer_list.html", locals(), context_instance=RequestContext(request))


# 删除客户
@csrf_exempt
@login_required
def del_cus(request):
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        cus_id = request.POST.get("cus_id", None)

        if cus_id is None or str(cus_id).strip() == "":
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        # 执行删除操作
        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            response["error"] = "未找到该客户!"
            return  HttpResponse(json.dumps(response), mimetype="application/json")

        customer = customer[0]
        for item in customer.machines:
            item.delete()
        customer.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception, e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def log(request):
    """
    客户更新记录
    :param request:
    :return:
    """
    logs = CoreLogger.objects(collection='customer').order_by('-create_time')
    return render_to_response("customer/customer_list_log.html", locals(), context_instance=RequestContext(request))



@csrf_exempt
@login_required
def tips(request):
    """
    客户小贴士
    :param request:
    :return:
    """
    response = {"success": False, "error": ""}
    if request.method == 'GET':
        try:
            cus_id = request.GET.get('cus_id')

            if not cus_id:
                response['error'] = '客户ID为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects(pk=cus_id)

            if len(customer) == 0:
                response['error'] = '未能获取客户对象!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = customer[0]
            tips = CustomerTip.objects(customer=customer, is_active=True).order_by('-create_time')

            t = get_template('customer/include/customer_tips_list.html')
            html = t.render(Context({'tips': tips, 'customer': customer}))

            response['success'] = True
            response['data'] = str(html)

            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def tips_create(request):
    """
    创建小贴士
    :param request:
    :return:
    """
    response = {"success": False, "error": ""}
    if request.method == 'POST':
        try:
            # 获取file
            file_obj = request.FILES.get('upload_file', None)
            file_name = None
            file_size = None
            if file_obj:
                file_name = file_obj.name
                file_size = file_obj.size

            cus_id = request.POST.get('cus_id')
            content = request.POST.get('content')

            if not cus_id:
                response['error'] = '客户ID为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects(pk=cus_id)

            if len(customer) == 0:
                response['error'] = '未能获取客户对象!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = customer[0]

            tip = CustomerTip()
            tip.customer = customer
            if file_obj:
                tip.file.put(file_obj)
                tip.file_name = file_name
                tip.file_size = file_size

            tip.is_active = True
            tip.content = content
            tip.create_time = datetime.datetime.now()
            tip.create_user = User.objects.get(pk=request.user.id)
            tip.save()

            response['data'] = {
                'id': str(tip.id),
                'cus_id': str(customer.id),
                'content': tip.content,
                'download': True if file_obj else False,
                'create_user': tip.create_user.username,
                'create_time': tip.create_time.strftime("%Y-%m-%d %H:%M:%S")
            }

            response['success'] = True
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def tips_del(request):
    """
    删除小贴士
    :param request:
    :return:
    """
    response = {"success": False, "error": ""}
    if request.method == 'POST':
        try:
            id = request.POST.get('id')

            if not id:
                response['error'] = '必要参数!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            tip = CustomerTip.objects(pk=id)

            if len(tip) == 0:
                response['error'] = '获取对象失败!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            tip = tip[0]
            tip.delete()
            response['success'] = True
            response['error'] = '删除成功!'
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def tips_download(request):
    """
    下载文件
    :param request:
    :return:
    """
    try:
        # 获取参数
        id = request.GET.get('id', None)

        if id is None or id == '':
            error = "必要参数为空!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 验证对象是否存在
        tip = CustomerTip.objects(pk=id)

        if len(tip) == 0:
            error = "未找到备注对象!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        tip = tip[0]

        if not tip.file:
            error = "该备注无文件!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        content = tip.file.read()
        response = HttpResponse(content)
        response['Content-Length'] = len(content)
        response['Content-Disposition'] = 'attachment; filename=%s' % tip.file_name.encode('utf-8')
        return response
    except Exception as e:
        error = "下载文件异常![%s]" % str(e)
        logger.error(error + getTraceBack())
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def tips_edit(request):
    """
    客户备注编辑
    :param request:
    :return:
    """
    if request.method == 'GET':
        try:
            id = request.GET.get('id')
            is_edit = True
            tip = CustomerTip.objects.get(pk=id)
            customer = tip.customer
            return render_to_response("customer/customer_tips_create.html", locals(), context_instance=RequestContext(request))
        except Exception as e:
            error = '程序异常![%s][%s]' % (e.message, getTraceBack())
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {'success': False, 'error': ''}
        try:
            # 获取file
            file_obj = request.FILES.get('tip_file', None)
            file_name = None
            file_size = None
            if file_obj:
                file_name = file_obj.name
                file_size = file_obj.size

            tip_id = request.POST.get('tip_id')
            tip_content = request.POST.get('tip_content')

            if not tip_id:
                response['error'] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            tip = CustomerTip.objects.get(pk=tip_id)
            if file_obj:
                tip.file.replace(file_obj)
                tip.file_name = file_name
                tip.file_size = file_size

            tip.content = tip_content
            tip.update_user = User.objects.get(pk=request.user.id)
            tip.update_time = datetime.datetime.now()
            tip.save()

            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def log_delete(request):
    """
    删除日志
    :param request:
    :return:
    """
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        json_param = request.POST.get("json", None)

        if not json_param:
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        json_param = json.loads(json_param)

        # 执行删除操作
        logs = CoreLogger.objects(pk__in=json_param)
        if len(logs) == 0:
            response["error"] = "未找到对应日志!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        for item in logs:
            item.delete()

        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception as e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def permission_view(request):
    """
    客户权限设置项
    :param request:
    :return:
    """
    if request.method == 'GET':
        # 已有设置项,只设置权限设置项
        settings = CustomerPermissionSettings.objects()
        value_type_list = CustomerPermissionSettings.get_value_type()
        return render_to_response("customer/customer_permission_view.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def permission_edit(request):
    """
    客户权限设置项
    :param request:
    :return:
    """
    if request.method == 'GET':
        # 已有设置项,只设置权限设置项
        settings = CustomerPermissionSettings.objects()
        value_type_list = CustomerPermissionSettings.get_value_type()
        return render_to_response("customer/customer_permission_edit.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {'success': False, 'error': ''}
        try:
            # 获取参数
            request_json = json.loads(request.POST.get("json"))
            # TODO 暂时清空数据库表
            CustomerPermissionSettings.objects.delete()

            for setting in request_json:
                setting_id = setting['setting_id']
                setting_name = setting['setting_name']
                setting_value = setting['setting_value']
                setting_value_type = setting['setting_value_type']
                setting_remark = setting['setting_remark']
                setting = CustomerPermissionSettings()
                if setting_id is not None:
                    setting.id = setting_id
                setting.name = setting_name
                setting.value = setting_value
                setting.value_type = setting_value_type
                setting.remark = setting_remark
                setting.save()

            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def permission_del(request):
    """
    客户权限设置项
    :param request:
    :return:
    """
    response = {"success": False, "error": ""}
    try:
        # 获取参数
        per_id = request.POST.get("id", None)
        if per_id is None or str(per_id).strip() == "":
            response["error"] = "权限Id为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        path = request.path
        is_sys = None
        if path == '/customer/system/list/':
            is_sys = True
        elif path == '/customer/list/':
            is_sys = False
        else:
            is_sys = False
        customers = Customer.objects(is_sys=is_sys).order_by('+tag')
        setting = CustomerPermissionSettings.objects(pk=per_id)
        if len(setting) == 0:
            response["error"] = "未找到该权限设置项!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        setting = setting[0]
        for customer in customers:
             perm_list = customer.permissions
             for permission in perm_list:
                 if permission == per_id and setting.name !='':
                     response["error"] = "该权限被用户[%s]使用,不能删除!" % str(customer.name)
                     return HttpResponse(json.dumps(response), mimetype="application/json")

        setting.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception as e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record(request):
    """
    添加升级记录
    :param request:
    :return:
    """
    global record_type
    global record_id
    if request.method == "GET":
        # 获取参数
        # 机器ID
        cus_id = request.GET.get('cus_id', None)
        record_type = request.GET.get('type', None)

        # 根据机器ID反查客户
        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer = customer[0]
        machines = customer.machines

        if not machines:
            error = '客户[%s][id=%s]名下无机器!' % (customer.name, cus_id)
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 查询客户包对象
        packages = CustomerPackage.objects(customer=customer).order_by("-create_time")

        if not packages:
            error = '客户[%s][id=%s]不存在客户包对象!' % (customer.name, cus_id)
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return render_to_response("customer/customer_deploy_record.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {"success": False, "error": ""}
        try:
            # 获取参数
            json_str = request.POST.get('json', None)

            if not json_str:
                response["error"] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            json_obj = json.loads(json_str)

            cus_id = json_obj.get('cus_id', None)
            customer_package_id = json_obj.get('customer_package_id', None)
            portal_upgrade_sql = json_obj.get('portal_upgrade_sql', None)
            deploy_user = json_obj.get('deploy_user', None)
            check_user = json_obj.get('check_user', None)
            is_checked = json_obj.get('is_checked', None)
            start_time = json_obj.get('start_time', None)
            end_time = json_obj.get('end_time', None)
            remark = json_obj.get('remark', None)

            if not cus_id or not customer_package_id or not deploy_user or not start_time or not end_time or not remark:
                response["error"] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects.get(pk=cus_id)
            customer_package = CustomerPackage.objects.get(pk=customer_package_id)
            start_time = datetime.datetime.strptime(start_time, DEFAULT_DATETIME)
            end_time = datetime.datetime.strptime(end_time, DEFAULT_DATETIME)

            # 保存参数

            if record_type == "add":
                record = CustomerDeployRecord()
                record.customer = customer
                record.cus_package = customer_package
                record.portal_upgrade_sql = portal_upgrade_sql
                record.start_time = start_time
                record.end_time = end_time
                record.deploy_user = deploy_user
                record.check_user = check_user
                record.is_checked = is_checked
                record.remark = remark
                record.create_time = datetime.datetime.now()
                record.create_user = User.objects.get(pk=request.user.id)
                record.save()
            elif record_type == 'edit':
                record = CustomerDeployRecord.objects.get(pk=record_id)
                record.customer = customer
                record.cus_package = customer_package
                record.portal_upgrade_sql = portal_upgrade_sql
                record.start_time = start_time
                record.end_time = end_time
                record.deploy_user = deploy_user
                record.check_user = check_user
                record.is_checked = is_checked
                record.remark = remark
                record.create_time = datetime.datetime.now()
                record.create_user = User.objects.get(pk=request.user.id)
                record.save()

            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % getTraceBack()
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record_list_edit(request):
    global record_id
    global record_type
    # global list_flag
    if request.method == 'GET':
        try:
            record_id = request.GET.get('id', None)
            flag = request.GET.get('flag', None)
            record_type = request.GET.get('type', None)
            if record_id is None:
                error = '编辑升级记录时ID为空!'
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
            if flag is not None:
                list_flag = flag
            record = CustomerDeployRecord.objects(pk=record_id)

            if len(record) == 0:
                error = "编辑的升级记录不存在!"
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

            record = record[0]
            customer = record.customer
            machines = customer.machines
            packages = CustomerPackage.objects(customer=customer).order_by("-create_time")
            remake = record.remark
            deploy_user = record.deploy_user
            check_user = record.check_user
            is_checked = record.is_checked
            start_time = record.start_time.strftime("%Y-%m-%d %H:%M:%S")
            end_time = record.end_time.strftime("%Y-%m-%d %H:%M:%S")
            portal_upgrade_sql = record.portal_upgrade_sql

            return render_to_response('customer/customer_deploy_record.html', locals(), context_instance=RequestContext(request))
        except Exception as e:
                error = '编辑用户异常![%s]' % str(e)
                logger.error(error + getTraceBack())
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
          error = '非法的请求方式!'
          logger.error(error)
          return render_to_response('item/temp.html', locals(),context_instance=RequestContext(request))


@csrf_exempt
@login_required
def deploy_record_list_email(request):
    response = {"success": False, "error": ""}
    if request.method == 'POST':
        try:
            id = request.POST.get('id', None)
            if id is None:
                    error = '编辑升级记录时ID为空!'
                    logger.error(error)
                    return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
            record = CustomerDeployRecord.objects(pk=id)

            if len(record) == 0:
                    error = "编辑的升级记录不存在!"
                    logger.error(error)
                    return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
            record = record[0]
            customer = record.customer
            check_user = record.check_user
            mail_title = '升级检查--[%s]'%str(customer.name)
            mail_message = get_mail_message(record)
            if mail_message == "":
                response["success"] = True
                response["error"] = "客户没有升级检查记录,发送邮件失败!"
                return HttpResponse(json.dumps(response), mimetype="application/json")
            is_checked = record.is_checked
            check_user = record.check_user
            if check_user == "" or check_user is None or check_user == "任意":
                    response["success"] = False
                    response["error"] = "尚未指定进行升级检查人员,发送邮件失败!"
                    return HttpResponse(json.dumps(response), mimetype="application/json")
            if is_checked is None or is_checked == '否' or is_checked == '':
                 mail_to = ['%s@thinktrader.net' % str(record.check_user)]
            else:
                 mail_to = ['xujun@thinktrader.net','majing@thinktrader.net', 'zhaoxu@thinktrader.net','limanli@thinktrader.net', 'zhaoshuailong@thinktrader.net', 'liuchao@thinktrader.net'
                             'dingyiran@thinktrader.net',  'xuzhihui@thinktrader.net', 'changjingde@thinktrader.net', 'libing@thinktrader.net',
                             'duanliangxin@thinktrader.net', 'duanxingxing@thinktrader.net',
                 ]
            send_mail(mail_title, mail_message, 'majing@thinktrader.net',mail_to,fail_silently=False)
            response["success"] = True
            response["error"] = "邮件发送成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
                response["error"]= "系统异常![%s]" %str(e)
                logger.error(response["error"] + getTraceBack())
                return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record_del(request):
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        id = request.POST.get("id", None)

        if id is None or str(id).strip() == "":
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        # 执行删除操作
        record = DeployRecord.objects(pk=id)
        if len(record) == 0:
            response["error"] = "未找到该记录!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        record = record[0]
        record.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception, e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_cus_record_del(request):
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        id = request.POST.get("id", None)

        if id is None or str(id).strip() == "":
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        # 执行删除操作
        record = CustomerDeployRecord.objects(pk=id)
        if len(record) == 0:
            response["error"] = "未找到该记录!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        record = record[0]
        record.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception, e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record_quick(request):
    response = {"success": False, "error": ""}

    if request.method == 'POST':
        try:
            # 先录入版本库
            file_obj = request.FILES.get('uploadFile', None)
            file_name = file_obj.name
            file_size = file_obj.size
            json_info = request.POST.get('json')
            remark_package = request.GET.get('remark_package')
            package_version = request.GET.get('package_version')
            package = Package()
            package.version = package_version
            package.json_info = json.dumps(json.loads(json_info), ensure_ascii=False).encode(ENCODE)
            package.is_enabled = True
            package_suffix = file_name[file_name.rindex('.') + 1:]
            # 写入流文件
            package.package.put(file_obj, content_type=CONTENT_TYPE[package_suffix])
            # 文件名
            package.package_full_name = file_name
            package.package_name = file_name[0:file_name.rindex('.')]
            package.package_suffix = package_suffix
            package.package_size = file_size
            package.remark = remark_package
            package.upload_user = User.objects(pk=request.user.id)[0]
            package.create_time = datetime.datetime.now()
            package.source = SOURCE_TEST
            package.save()

            # 记录升级记录
            # 获取参数
            machine_id = request.GET.get('machine_id', None)
            cus_id = request.GET.get('cus_id', None)
            # 开始时间
            start_time = request.GET.get('start_time', None)
            if start_time is not None:
                start_time = datetime.datetime.strptime(start_time, DEFAULT_DATETIME)
            # 结束时间
            end_time = request.GET.get('end_time', None)
            if end_time is not None:
                end_time = datetime.datetime.strptime(end_time, DEFAULT_DATETIME)
            # 备注
            remark_deploy = request.GET.get('remark_deploy', None)
            deploy_user = request.GET.get('deploy_user', None)
            # TODO 加入校验合法性
            machine = Machine.objects(pk=machine_id)[0]
            customer = Customer.objects(pk=cus_id)[0]

            # 保存参数
            record = DeployRecord()
            record.customer = customer
            record.machine = machine
            record.new_version = package
            record.start_time = start_time
            record.end_time = end_time
            record.remark = remark_deploy
            record.deploy_user = request.user
            record.create_user = User.objects(pk=request.user.id)[0]
            record.create_time = datetime.datetime.now()
            record.save()

            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception, e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        response["error"] = "请使用POST方法提交!"
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record_list(request):
    """
    查看升级记录
    :param request:
    :return:
    """
    if request.method == "GET":
        # 获取参数
        # 机器ID
        cus_id = request.GET.get('cus_id', None)

        # 根据机器ID反查客户
        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer = customer[0]

        machines = customer.machines

        if not machines:
            error = '请为客户[%s]添加机器!' % customer.name
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 查询升级记录
        cus_records = CustomerDeployRecord.objects(customer=customer).order_by("-start_time")

        return render_to_response("customer/customer_deploy_record_list.html", locals(), context_instance=RequestContext(request))
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

# 是否有正在执行的指令任务
compile_task_running = False


@csrf_exempt
@login_required
def all_deploy_record_list(request):

    """
    客户升级列表
    :param request:
    :return:
    """
    if request.method == 'GET':
        after_range_num = 2

        try:
            page = int(request.GET.get("page", 1))
            if page < 1:
                page = 1
        except ValueError:
            page = 1
        paginator = Paginator(CustomerDeployRecord.objects().order_by("-start_time"), PAGE_SIZE)
        befor_range_num = 1
        try:
            cus_records_list = paginator.page(page)
        except(EmptyPage, InvalidPage, PageNotAnInteger):
            cus_records_list = paginator.page(paginator.num_pages)
        if page >= after_range_num:
            page_range = paginator.page_range[page - after_range_num:page + befor_range_num]
        else:
            page_range = paginator.page_range[0:int(page) + befor_range_num]
        cus_records=CustomerDeployRecord.objects.order_by('-start_time')
        return render_to_response("customer/customer_all_deploy_record_list.html",  {'cus_records':cus_records_list,'page_range':page_range,'request':request})
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def all_deploy_record_list_search(request):

    """
    客户升级列表--查询
    :param request:
    :return:
    """
    if request.method == 'GET':
        text = request.GET.get('search',None)
        records = CustomerDeployRecord.objects().order_by("-start_time")
        cus_records = []

        for record in records:
            if text == record.customer.name or text == record.is_checked or text == record.check_user or text == record.deploy_user:
                 cus_records.append(record)
        return render_to_response("customer/customer_all_deploy_record_list_search.html", locals(), context_instance=RequestContext(request))
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def all_deploy_record_unchecked_list(request):
    if request.method == 'GET':

        cus_records=CustomerDeployRecord.objects().order_by('-start_time')
        results = []
        for record in cus_records:
            if record.is_checked != '是':
                results.append(record)
        return render_to_response("customer/customer_all_deploy_unchecked_list.html", locals(), context_instance=RequestContext(request))
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def deploy_record_check_list(request):
      response = {"success": False, "error": ''}
      if request.method == 'GET':
             id = request.GET.get("id", None)
             if id is None :
                 response['error'] = "客户ID为空!"
                 return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
             customer = Customer.objects.get(pk=id)
             #查看所有的升级检查记录
             check_record = CustomerDeployCheckRecord.objects(customer=customer).order_by("-start_time")
             return render_to_response("customer/customer_deploy_record_check_list.html", locals(), context_instance=RequestContext(request))
      else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
# 是否有正在执行的指令任务
compile_task_running = False


@csrf_exempt
@login_required
def deploy_record_checkupdate(request):
      response = {"success": False, "error": '', "data":{}}
      response["data"] = {'xt':2, 'nginx':2, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
      if request.method == 'POST':
        try:
             id = request.POST.get("id", None)
             if id is None :
                 response['error'] = "客户ID为空!"
                 return HttpResponse(json.dumps(response), mimetype="application/json")
             customer = Customer.objects.get(pk=id)
             machines = customer.machines
             machine_num  = len(machines)
             cus_modules = customer.modules
             module_list=[]
             for module in cus_modules:
                 if module.group == "XT模块":
                     module_list.append(module)
             module_num = len(module_list)
             # 远程登录部署机器
             if machine_num == 1:
                 host = machines[0].host
                 port =  machines[0].port
                 name =  machines[0].username
                 passwd =  machines[0].password

                 ssh = paramiko.SSHClient()
                 ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                 ssh.connect(host, port, name, passwd, timeout=5)
                 #xt服务检查
                 is_success = get_update_check_Xt(ssh, module_num)
                 if is_success:
                     response["data"] = {'xt':0, 'nginx':2, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                 else:
                     response["data"] = {'xt':1, 'nginx':2, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "Xt服务没有完全启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
                 #nginx服务检查
                 is_success = get_update_check_Nginx(ssh)
                 if is_success:
                     response["data"] = {'xt':0, 'nginx':0, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                 else:
                     response["data"] = {'xt':0, 'nginx':1, 'python':2, 'lua':2, 'server':2,'ng_nginx':2,'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "Nginx服务没有完全启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
                 #Python服务检查
                 is_success = get_update_check_Python(ssh)
                 if is_success:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':1, 'lua':2,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "python服务没有完全启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
                 #lua服务检查
                 is_success = get_update_check_Lua(ssh, module_num)
                 if is_success:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':2,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':1, 'server':2,'ng_nginx':2,'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "lua服务没有完全启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
                 #监控XtService
                 is_success = get_nginx_xtserver(ssh)
                 if is_success:
                      response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':2, 'mysql':-1,'keepalived':-1}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0, 'server':1,'ng_nginx':2,'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "XtService服务没有启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
                 #监控nginx
                 is_success = get_nginx_nginx(ssh)
                 if is_success:
                      response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':0,'mysql':-1, 'keepalived':-1}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0, 'server':0,'ng_nginx':1,'mysql':-1,'keepalived':-1}
                     response["success"] = False
                     response["error"] = "nginx服务没有启动!"
                     ssh.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")
             elif machine_num == 2:
                 response["data"] = {'xt':2, 'nginx':2, 'python':2, 'lua':2, 'mysql':2,'server':2,'ng_nginx':2, 'keepalived':2}
                 host_first = machines[0].host
                 port_first =  machines[0].port
                 name_first =  machines[0].username
                 passwd_first =  machines[0].password

                 host_sec = machines[1].host
                 port_sec =  machines[1].port
                 name_sec =  machines[1].username
                 passwd_sec =  machines[1].password

                 ssh_master = paramiko.SSHClient()
                 ssh_master.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                 ssh_master.connect(host_first, port_first, name_first, passwd_first, timeout=5)

                 ssh_slave = paramiko.SSHClient()
                 ssh_slave.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                 ssh_slave.connect(host_sec, port_sec, name_sec, passwd_sec, timeout=5)

                 first_flag = get_update_check_Xt(ssh_master, module_num)
                 second_flag = get_update_check_Xt(ssh_slave, module_num)
                 if (first_flag == True and second_flag == False) or (first_flag == False and second_flag == True):
                     response["data"] = {'xt':0, 'nginx':2, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2,  'keepalived':2}
                 else:
                     response["data"] = {'xt':1, 'nginx':2, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2,  'keepalived':2}
                     response["success"] = False
                     response["error"] = "Xt服务没有完全启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_update_check_Nginx(ssh_master)
                 second_flag = get_update_check_Nginx(ssh_slave)
                 if first_flag == True and  second_flag == True:
                     response["data"] = {'xt':0, 'nginx':0, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':1, 'python':2, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "Nginx服务没有完全启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_update_check_Python(ssh_master)
                 second_flag = get_update_check_Python(ssh_slave)
                 if first_flag == True  and second_flag == True:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':1, 'lua':2,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "python服务没有完全启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_update_check_Lua(ssh_master, module_num)
                 second_flag = get_update_check_Lua(ssh_slave, module_num)
                 if (first_flag == True and second_flag == False) or (first_flag == False and second_flag == True):
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':1,'server':2,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "lua服务没有完全启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_nginx_xtserver(host_first)
                 second_flag = get_nginx_xtserver(host_sec)
                 if first_flag == True  and second_flag == True:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':1, 'lua':0,'server':1,'ng_nginx':2, 'mysql':2, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "XtService服务没有启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_nginx_xtserver(host_first)
                 second_flag = get_nginx_xtserver(host_sec)
                 if first_flag == True  and second_flag == True:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':0, 'mysql':2, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':1, 'lua':0,'server':0,'ng_nginx':1, 'mysql':2, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "nginx服务没有启动!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 first_flag = get_update_check_Mysql(host_first)
                 second_flag = get_update_check_Mysql(host_sec)
                 if (first_flag == True and second_flag == False) or (first_flag == False and second_flag == True):
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':0, 'mysql':0, 'keepalived':2}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':0, 'mysql':1, 'keepalived':2}
                     response["success"] = False
                     response["error"] = "数据库同步更新有错误!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="application/json")

                 is_success = get_update_check_Keepalived(ssh_master, ssh_slave)
                 if is_success:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0,'server':0,'ng_nginx':0, 'mysql':0, 'keepalived':0}
                 else:
                     response["data"] = {'xt':0, 'nginx':0, 'python':0, 'lua':0, 'server':0,'ng_nginx':0,'mysql':0, 'keepalived':1}
                     response["success"] = False
                     response["error"] = "keepalived主备机不能正常切换!"
                     ssh_master.close()
                     ssh_slave.close()
                     return HttpResponse(json.dumps(response), mimetype="appli7cation/json")


                 ssh_master.close()
                 ssh_slave.close()

             response["success"] = True
             response["error"] = "检查结束!"
             return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception, e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_record_check_create(request):
    if request.method == "GET":
        cus_id = request.GET.get('cus_id', None)
        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer = customer[0]
        machines = customer.machines
        machine_num = len(machines)
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return render_to_response("customer/customer_deploy_record_check.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {"success": False, "error": ""}
        try:
            # 获取参数
            json_str = request.POST.get('json', None)

            if not json_str:
                response["error"] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            json_obj = json.loads(json_str)

            cus_id = json_obj.get('cus_id', None)
            check_user = json_obj.get('check_user', None)
            start_time = json_obj.get('start_time', None)
            end_time = json_obj.get('end_time', None)
            remark = json_obj.get('remark', None)

            if not cus_id or not check_user or not start_time or not end_time or not remark:
                response["error"] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects.get(pk=cus_id)
            machines = customer.machines
            start_time = datetime.datetime.strptime(start_time, DEFAULT_DATETIME)
            end_time = datetime.datetime.strptime(end_time, DEFAULT_DATETIME)

            # 保存参数
            record = CustomerDeployCheckRecord()
            record.customer = customer
            record.start_time = start_time
            record.end_time = end_time
            record.check_user = check_user
            record.remark = remark
            record.create_time = datetime.datetime.now()
            record.create_user = User.objects.get(pk=request.user.id)
            record.save()

            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % getTraceBack()
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")

@csrf_exempt
@login_required
def deploy_record_check_del(request):
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        id = request.POST.get("id", None)
        if id is None or str(id).strip() == "":
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        # 执行删除操作
        record = CustomerDeployCheckRecord.objects(pk=id)
        if len(record) == 0:
            response["error"] = "未找到该记录!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        record = record[0]
        record.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception, e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def compiling(request):
    """
    编译升级
    :param request:
    :return:
    """
    if request.method == "GET":
        global compileINFO
        compileINFO = ""
        # 获取参数
        # 机器ID
        cus_id = request.GET.get('cus_id', None)
        if cus_id is None:
            error = '重要参数不能为空!'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 客户
        customer = customer[0]
        # 客户的模块
        modules = customer.modules
        # 编译所需参数
        module_file_raw_path = {}
        # 查找编译机
        machines = Machine.objects(type=1, os=OS_TYPE_LINUX)

        if modules is None or len(modules) == 0:
            error = '客户[id=%s][name=%s]无任何模块无法编译!' % (cus_id, customer.name)
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 记录所有模块参数名
        program_names = PROGRAM_LIST
        defaultInfo = CustomerDefaultBranch.objects(customer=customer)
        branchInfos = BranchInfo.objects(programName__in=program_names).order_by("-branchTag")
        return render_to_response("customer/customer_compile.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {"success": False, "error": "", 'log': []}

        global compile_task_running
        global compileINFO
        compileINFO = ""

        # 查询编译日志,找到最新一条记录
        if compile_task_running:
            response["error"] = "编译机正在执行任务,请稍候!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        compile_task_running = True
        try:
            # 获取参数
            compileINFO = "获取参数"
            req_json = request.POST.get('json', None)
            req_json = json.loads(req_json)

            machine_id = req_json['machine_id']
            updates = req_json['updates']
            compiles = req_json['compiles']
            cleans = req_json['cleans']
            remark = ''

            if not updates and not cleans and not compiles:
                response["error"] = "请至少选择一项指令!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            # 生成特殊数据结构来标识任务
            compileINFO = "生成特殊数据结构来标识任务"
            tasks = {}
            for programName, branchTag in updates.iteritems():
                ops = tasks.get(programName, None)
                if ops is None:
                    tasks[programName] = [branchTag, False, False, False]
                tasks[programName][1] = True

            for programName, branchTag in cleans.iteritems():
                ops = tasks.get(programName, None)
                if ops is None:
                    tasks[programName] = [branchTag, False, False, False]
                tasks[programName][2] = True

            for programName, branchTag in compiles.iteritems():
                ops = tasks.get(programName, None)
                if ops is None:
                    tasks[programName] = [branchTag, False, False, False]
                tasks[programName][3] = True

            # 确认指定机器是否处于待编译状态
            compileINFO = "确认指定机器是否处于待编译状态"
            machine = Machine.objects.get(pk=machine_id)

            if machine.type != 1:
                response["error"] = "不能对非编译机下达指令!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            svn_utils = SvnUtils()

            # 记录任务执行日志,响应给前台
            compileINFO = "记录任务执行日志"
            log_list = []
            task_flag = True
            # 开始执行任务
            compileINFO = "开始执行任务，请耐心等待..."
            for programName, ops in tasks.iteritems():
                branchTag = ops[0]
                path = svn_utils.get_local_path(programName, branchTag)


                try:
                    # 获取branch_info对象
                    branch_info = BranchInfo.objects.get(programName=programName, branchTag=branchTag)
                    compileINFO = "获取branch_info对象"

                    # 获取当前revision
                    compileINFO = "获取当前revision"
                    revision = svn_utils.get_local_svn_info(path)['revision']


                    # 跳转到当前目录
                    os.chdir(path)

                    # 执行更新任务
                    compileINFO = "执行更新任务"
                    if ops[1]:
                        update_record = None
                        try:
                            update_record = get_record_instance(machine, branch_info, revision, CMD_SVN_UP, request.user.id, remark)
                            p = Popen(["svn", "up"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                            outStr, errorStr = p.communicate()
                            if len(errorStr) > 0:
                                update_record.end_time = datetime.datetime.now()
                                update_record.status = RESULT_TYPE_FAILURE
                                update_record.remark = "[%s]SVN更新任务失败：%s" % (update_record.remark, errorStr)
                                update_record.save()
                                task_flag = False
                                log_list.append('path:[%s] --> SVN更新任务异常![%s]' % (path, errorStr))
                                continue
                            update_record.end_time = datetime.datetime.now()
                            update_record.status = RESULT_TYPE_SUCCESS
                            update_record.save()
                            log_list.append('path:[%s] --> SVN更新任务成功!' % path)
                        except Exception as e:
                            errorStr = '[%s:%s]' % (e.message, getTraceBack())
                            update_record.end_time = datetime.datetime.now()
                            update_record.status = RESULT_TYPE_FAILURE
                            update_record.remark = "[%s]SVN更新任务异常：%s" % (update_record.remark, errorStr)
                            update_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> SVN更新任务异常![%s]' % (path, errorStr))
                            continue
                    # 执行清理任务
                    compileINFO = "执行清理任务"
                    if ops[2]:
                        clean_record = None
                        try:
                            clean_record = get_record_instance(machine, branch_info, revision, CMD_MAKE_CLEAN, request.user.id, remark)
                            p = Popen(["make", "clean"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                            outStr, errorStr = p.communicate()
                            if len(errorStr) > 0:
                                clean_record.end_time = datetime.datetime.now()
                                clean_record.status = RESULT_TYPE_FAILURE
                                clean_record.remark = "[%s]清理任务失败：%s" % (clean_record.remark, errorStr)
                                clean_record.save()
                                task_flag = False
                                log_list.append('path:[%s] --> 清理任务异常![%s]' % (path, errorStr))
                                continue
                            clean_record.end_time = datetime.datetime.now()
                            clean_record.status = RESULT_TYPE_SUCCESS
                            clean_record.save()
                            log_list.append('path:[%s] --> 清理任务成功!' % path)
                        except Exception as e:
                            errorStr = '[%s:%s]' % (e.message, getTraceBack())
                            clean_record.end_time = datetime.datetime.now()
                            clean_record.status = RESULT_TYPE_FAILURE
                            clean_record.remark = "[%s]清理任务异常：%s" % (clean_record.remark, errorStr)
                            clean_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> 清理任务异常![%s]' % (path, errorStr))
                            continue

                    # 执行编译任务
                    compileINFO = "正在编译" + branchTag + ", 请耐心等待..."
                    if ops[3]:
                        compile_record = None
                        try:
                            compile_record = get_record_instance(machine, branch_info, revision, CMD_COMPILE, request.user.id, remark)
                            p = Popen(["make", "-j8", "all", "USER=deploy"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                            outStr, errorStr = p.communicate()
                            if len(errorStr) > 0:
                                compile_record.end_time = datetime.datetime.now()
                                compile_record.status = RESULT_TYPE_FAILURE
                                compile_record.remark = "[%s]编译任务失败：%s" % (compile_record.remark, errorStr)
                                compile_record.save()
                                task_flag = False
                                log_list.append('path:[%s] --> 编译任务失败![%s]' % (path, errorStr))
                                continue
                            compile_record.end_time = datetime.datetime.now()
                            compile_record.status = RESULT_TYPE_SUCCESS
                            compile_record.save()
                            log_list.append('path:[%s] --> 编译任务成功!' % path)
                        except Exception as e:
                            errorStr = '[%s:%s]' % (e.message, getTraceBack())
                            logger.error('编译异常！' + errorStr)
                            compile_record.end_time = datetime.datetime.now()
                            compile_record.status = RESULT_TYPE_FAILURE
                            compile_record.remark = "[%s]编译任务异常：%s" % (compile_record.remark, errorStr)
                            compile_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> 编译任务异常![%s]' % (path, errorStr))
                            continue
                except Exception as e:
                    error = '[%s:%s]' % (e.message, getTraceBack())
                    logger.error("执行server指令任务异常![path=%s][error=%s]" % (path, error))
                    task_flag = False
                    log_list.append('path:[%s] --> 执行指令任务异常![%s]' % (path, error))

            if not task_flag:
                log_list.append('任务异常终止,可能有任务未执行...')

            compileINFO = branchTag + "分支编译完成！"
            response["success"] = task_flag
            response["log"] = log_list
            response["error"] = "执行成功!" if task_flag else '执行失败!'
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception, e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
        finally:
            compile_task_running = False

#编译进度查询
def compileProcessInfo(request):
    global compileINFO
    if request.method == "GET":
        response = {"success": True, "compileINFO": compileINFO}
        return HttpResponse(json.dumps(response), mimetype="application/json")

def get_record_instance(machine, branch_info, revision, cmd, user_id, remark):
    """
    生成操作记录对象
    :param machine:
    :param branch_info:
    :param revision:
    :param cmd:
    :param user:
    :param remark:
    :return:
    """
    record = CompilingUpdateRecord()
    record.machine = machine
    record.branch_info = branch_info
    record.revision = revision
    record.start_time = datetime.datetime.now()
    record.cmd = cmd
    record.status = RESULT_TYPE_RUNNING
    record.operate_user = User.objects.get(pk=user_id)
    record.remark = remark
    record.save()
    return record


def get_param_name(module):
    """
    以模块为单位获取原始路径参数名
    :param module:
    :return:
    """
    param_name = []
    files = module.files

    def get_param_replace(raw_path):
        """
        原始路径(替换用)
        :param raw_path:
        :return:
        """
        return re.findall(r'{{[a-zA-Z0-9_ ]+}}', raw_path)

    for file in files:
        raw_path = file.rawPath
        param_replace = get_param_replace(raw_path)
        for item in param_replace:
            name = re.findall(r'[a-zA-Z0-9_]+', item)[0]
            param_name.append(str(name))
    param_name = list(set(param_name))
    param_name.sort()
    return param_name


@csrf_exempt
@login_required
def compiling_status(request):
    """
    查询编译任务执行状态
    :param request:
    :return:
    """
    if request.method == "GET":
        response = {"success": False, "error": ""}

        try:
            # 参数
            program_name = request.GET.get('program_name', None)
            branch_tag = request.GET.get('branch_tag', None)
            logger.info('program_name=%s, branch_tag=%s' % (program_name, branch_tag))

            if program_name is None or branch_tag is None:
                response["error"] = '必要参数为空!'
                return HttpResponse(json.dumps(response), mimetype='application/json')

            svn_utils= SvnUtils()

            svn_url = svn_utils.get_svn_url(program_name, branch_tag)
            current_revision = svn_utils.get_current_svn_revision(svn_url)
            local_path = svn_utils.get_local_path(program_name, branch_tag)
            local_revision = svn_utils.get_local_svn_info(local_path)['revision']
            # 查看对象相关外链信息
            externals = svn_utils.get_local_svn_externals(local_path)
            externals_local_revision=[]
            externals_current_revision=[]
            befor_x=''
            for external in externals:
                if external[2].find('/server5/')>0:
                    arr=external[2].split(SVN_ROOT + 'server5/')[1].split('/',2)
                else:
                    arr=external[2].split(SVN_ROOT)[1].split('/',2)
                external_name=arr[0]
                external_branch_tag=arr[1]
                x=external_name+'/'+external_branch_tag
                if befor_x.find(x)< 0:
                    externals_local_revision.append('<br/>'+x+' '+str(external[1]))
                    externals_current_revision.append('<br/>'+x+' '+str(external[3]))
                    befor_x+=x
            branch_status = {
                'update': {
                     'current_revision': current_revision,
                     'local_revision': local_revision,
                     'externals_local_revision':externals_local_revision,
                     'externals_current_revision':externals_current_revision
                },
                'clean': {
                    'current_revision': current_revision,
                    'local_revision': local_revision,
                    'externals_local_revision':externals_local_revision,
                    'externals_current_revision':externals_current_revision,
                    'last_execute_start_time': None,
                    'last_execute_end_time': None,
                    'last_execute_revision': None,
                    'status': None
                },
                'compile': {
                    'current_revision': current_revision,
                    'local_revision': local_revision,
                    'externals_local_revision':externals_local_revision,
                    'externals_current_revision':externals_current_revision,
                    'last_execute_start_time': None,
                    'last_execute_end_time': None,
                    'last_execute_revision': None,
                    'status': None
                }
            }

           # 查看BranchInfo信息
            branchInfo = svn_utils.get_branch_from_program_tag(program_name, branch_tag)
            update_record = CompilingUpdateRecord.objects(branch_info=branchInfo, cmd=CMD_SVN_UP).order_by('-start_time')
            clean_record = CompilingUpdateRecord.objects(branch_info=branchInfo, cmd=CMD_MAKE_CLEAN).order_by('-start_time')
            compile_record = CompilingUpdateRecord.objects(branch_info=branchInfo, cmd=CMD_COMPILE).order_by('-start_time')

            if len(update_record) != 0:
                update_record = update_record[0]
                branch_status['update']['status'] = update_record.status
            if len(clean_record) != 0:
                clean_record = clean_record[0]
                branch_status['clean']['last_execute_start_time'] = clean_record.start_time.strftime("%Y-%m-%d %H:%M:%S") if clean_record.start_time else '-'
                branch_status['clean']['last_execute_end_time'] = clean_record.end_time.strftime("%Y-%m-%d %H:%M:%S") if clean_record.end_time else '-'
                branch_status['clean']['last_execute_revision'] = clean_record.revision
                branch_status['clean']['status'] = clean_record.status
            if len(compile_record) != 0:
                compile_record = compile_record[0]
                branch_status['compile']['last_execute_start_time'] = compile_record.start_time.strftime("%Y-%m-%d %H:%M:%S") if compile_record.start_time else '-'
                branch_status['compile']['last_execute_end_time'] = compile_record.end_time.strftime("%Y-%m-%d %H:%M:%S") if compile_record.end_time else '-'
                branch_status['compile']['last_execute_revision'] = compile_record.revision
                branch_status['compile']['status'] = compile_record.status
            response["success"] = True
            response["data"] = branch_status
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")

@csrf_exempt
@login_required
def onekey_update(request):
    response = {"success": False, "error": ''}
    global deployINFO
    global deployPercent
    global compileINFO
    deployINFO = ""
    compileINFO = ""
    deployPercent = 0
    if request.method == "GET":
        cus_id = request.GET.get("cus_id", None)
        customer = Customer.objects.get(pk=cus_id)
        machines = Machine.objects(type=1, os=OS_TYPE_LINUX)

        if not machines:
            error = '无编译机!'
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 获取所有可用PortalPackage
        program_names = PROGRAM_LIST
        packages = PortalDefaultBranch.objects(customer=customer)
        defaultInfo = CustomerDefaultBranch.objects(customer=customer)
        packages = PortalDefaultBranch.objects(customer=customer)
        branchInfos = BranchInfo.objects(programName__in=program_names).order_by("-branchTag")
        portal_packages = PortalPackage.objects(is_enabled=True).order_by('-svn_version')
        return render_to_response("customer/customer_onekey_update.html", locals())

    elif request.method == "POST":

        deployINFO = "开始部署，请耐心等待..."
        deployPercent = 0

        program_names = PROGRAM_LIST
        remark = ''
        portal_upgrade_sql=''
        req_json = request.POST.get('json', None)
        req_json = json.loads(req_json)

        machine_id = req_json['machine_id']
        updates = req_json['updates']
        compiles = req_json['compiles']
        cleans = req_json['cleans']
        cus_id = req_json['cus_id']
        portal_package_id = req_json['portal_package']

        branchMap = req_json["params"]

        if cus_id is None:
            error = '重要参数不能为空!'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        #查找客户
        customer = Customer.objects(pk=cus_id)
        customer = customer[0]
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        machines = customer.machines

        machine = machines[0]
        # 找需要更新编译的程序分支(quoter单拿出来
        svn_utils = SvnUtils()
        user_id = request.user.id

        # 生成特殊数据结构来标识任务
        tasks = {}
        for programName, branchTag in updates.iteritems():
            ops = tasks.get(programName, None)
            if ops is None:
                tasks[programName] = [branchTag, False, False, False]
            tasks[programName][1] = True

        for programName, branchTag in cleans.iteritems():
            ops = tasks.get(programName, None)
            if ops is None:
                tasks[programName] = [branchTag, False, False, False]
            tasks[programName][2] = True

        for programName, branchTag in compiles.iteritems():
            ops = tasks.get(programName, None)
            if ops is None:
                tasks[programName] = [branchTag, False, False, False]
            tasks[programName][3] = True

        # 确认指定机器是否处于待编译状态
        machine = Machine.objects.get(pk=machine_id)

        if machine.type != 1:
            response["error"] = "不能对非编译机下达指令!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        svn_utils = SvnUtils()

        # 记录任务执行日志,响应给前台
        log_list = []
        task_flag = True
        # 开始执行任务
        for programName, ops in tasks.iteritems():
            branchTag = ops[0]
            path = svn_utils.get_local_path(programName, branchTag)


            try:
                # 获取branch_info对象
                branch_info = BranchInfo.objects.get(programName=programName, branchTag=branchTag)

                # 获取当前revision
                revision = svn_utils.get_local_svn_info(path)['revision']
               # svn_url=svn_utils.get_local_svn_info(path)['url']

                # 跳转到当前目录
                os.chdir(path)


                # 执行更新任务
                if ops[1]:
                    update_record = None
                    try:
                        update_record = get_record_instance(machine, branch_info, revision, CMD_SVN_UP, request.user.id, remark)
                        p = Popen(["svn", "up"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                        outStr, errorStr = p.communicate()
                        if len(errorStr) > 0:
                            update_record.end_time = datetime.datetime.now()
                            update_record.status = RESULT_TYPE_FAILURE
                            update_record.remark = "[%s]SVN更新任务失败：%s" % (update_record.remark, errorStr)
                            update_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> SVN更新任务异常![%s]' % (path, errorStr))
                            continue
                        update_record.end_time = datetime.datetime.now()
                        update_record.status = RESULT_TYPE_SUCCESS
                        update_record.save()
                        log_list.append('path:[%s] --> SVN更新任务成功!' % path)
                        deployINFO = "SVN更新任务成功!"
                        deployPercent = 5
                    except Exception as e:
                        errorStr = '[%s:%s]' % (e.message, getTraceBack())
                        update_record.end_time = datetime.datetime.now()
                        update_record.status = RESULT_TYPE_FAILURE
                        update_record.remark = "[%s]SVN更新任务异常：%s" % (update_record.remark, errorStr)
                        update_record.save()
                        task_flag = False
                        log_list.append('path:[%s] --> SVN更新任务异常![%s]' % (path, errorStr))
                        continue
                # 执行清理任务
                if ops[2]:
                    clean_record = None
                    try:
                        clean_record = get_record_instance(machine, branch_info, revision, CMD_MAKE_CLEAN, request.user.id, remark)
                        p = Popen(["make", "clean"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                        outStr, errorStr = p.communicate()
                        if len(errorStr) > 0:
                            clean_record.end_time = datetime.datetime.now()
                            clean_record.status = RESULT_TYPE_FAILURE
                            clean_record.remark = "[%s]清理任务失败：%s" % (clean_record.remark, errorStr)
                            clean_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> 清理任务异常![%s]' % (path, errorStr))
                            continue
                        clean_record.end_time = datetime.datetime.now()
                        clean_record.status = RESULT_TYPE_SUCCESS
                        clean_record.save()
                        log_list.append('path:[%s] --> 清理任务成功!' % path)
                        deployINFO = "清理任务成功!"
                        deployPercent = 10
                    except Exception as e:
                        errorStr = '[%s:%s]' % (e.message, getTraceBack())
                        clean_record.end_time = datetime.datetime.now()
                        clean_record.status = RESULT_TYPE_FAILURE
                        clean_record.remark = "[%s]清理任务异常：%s" % (clean_record.remark, errorStr)
                        clean_record.save()
                        task_flag = False
                        log_list.append('path:[%s] --> 清理任务异常![%s]' % (path, errorStr))
                        continue

                # 执行编译任务
                if ops[3]:
                    compile_record = None
                    try:
                        compile_record = get_record_instance(machine, branch_info, revision, CMD_COMPILE, request.user.id, remark)
                        p = Popen(["make", "-j8", "all", "USER=deploy"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
                        outStr, errorStr = p.communicate()
                        if len(errorStr) > 0:
                            compile_record.end_time = datetime.datetime.now()
                            compile_record.status = RESULT_TYPE_FAILURE
                            compile_record.remark = "[%s]编译任务失败：%s" % (compile_record.remark, errorStr)
                            compile_record.save()
                            task_flag = False
                            log_list.append('path:[%s] --> 编译任务失败![%s]' % (path, errorStr))
                            continue
                        compile_record.end_time = datetime.datetime.now()
                        compile_record.status = RESULT_TYPE_SUCCESS
                        compile_record.save()
                        log_list.append('path:[%s] --> 编译任务成功!' % path)
                        deployINFO = "编译成功！"
                        deployPercent = 20
                    except Exception as e:
                        errorStr = '[%s:%s]' % (e.message, getTraceBack())
                        logger.error('编译异常！' + errorStr)
                        compile_record.end_time = datetime.datetime.now()
                        compile_record.status = RESULT_TYPE_FAILURE
                        compile_record.remark = "[%s]编译任务异常：%s" % (compile_record.remark, errorStr)
                        compile_record.save()
                        task_flag = False
                        log_list.append('path:[%s] --> 编译任务异常![%s]' % (path, errorStr))
                        continue
            except Exception as e:
                error = '[%s:%s]' % (e.message, getTraceBack())
                logger.error("执行server指令任务异常![path=%s][error=%s]" % (path, error))
                task_flag = False
                log_list.append('path:[%s] --> 执行指令任务异常![%s]' % (path, error))

        if not task_flag:
            log_list.append('任务异常终止,可能有任务未执行...')
        # 创建机器包
        #机器包中的分支选择和更新编译的分支是一样的
        program_nas = [TT_SERVICE, BROKER, QUOTER]


        machine_id_list = []
        for machine in machines:
            machine_id_list.append(machine.id)

        if len(machines) != len(machine_id_list):
            response['error'] = '未能获取全部机器!'

        user = User.objects.get(pk=request.user.id)

        flag = True
        error_info = ''

        # make a UUID based on the host ID and current time
        base_uuid = str(uuid.uuid1())
        now = datetime.datetime.now()
        install_package_list = []

        # 开始生成程序包
        for machine in machines:
            one_flag, error_info_item, install_package = generator_cus_machine_package(customer, machine, branchMap, user, remark)
            if not one_flag:
                flag = False
            else:
                install_package_list.append(install_package)
            error_info += '\n\n'
            error_info += '<br>'
            error_info += error_info_item

        # 设置必要属性,保存Server包对象
        if flag:
            for install_package_item in install_package_list:
                install_package_item.create_time = now
                install_package_item.group_key = base_uuid
                install_package_item.save()

        deployINFO = "Server Package已生成"
        deployPercent = 25
        #serverpackages为机器包 已生成
        #创建客户包
        #portal包
        portal_package = PortalPackage.objects(pk=portal_package_id)

        if not portal_package:
            response['error'] = '未找到对应Portal包!'
            return HttpResponse(json.dumps(response), mimetype="application/json")

        portal_package = portal_package[0]
        #server包就是serverpackages

        if not install_package_list:
            response['error'] = '未找到对应Server包!'
            return HttpResponse(json.dumps(response), mimetype="application/json")

        user = User.objects.get(pk=request.user.id)

        deployINFO = "Portal Package已生成"
        deployPercent = 30
        #生成客户包（得到客户包的信息）

        customer_pack = customerpackage_create(customer, install_package_list, portal_package, portal_upgrade_sql, user, remark)

        #读取机器包的ssh 若可以远程部署 则无需生成客户包 直接部署 否则生成客户包,下载客户包
        res_list = list()
        customerStartTimen = datetime.datetime.now()

        #获取所有portal包
        if machine.host:

            content = portal_package.package.read()
            portalIO = StringIO(content)

            # 获得customerpackage的IO流
            for serverpackage in install_package_list:
                startTime = datetime.datetime.now()
                machine = serverpackage.machine
                stringIO = StringIO(gen_update_package(serverpackage))

                # 建立连接
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(machine.host, machine.port, username=machine.username, password=machine.password)
                    sftp = paramiko.SFTPClient.from_transport(client.get_transport())
                    deployINFO = "已和服务器建立连接"
                    deployPercent = 40
                except Exception as e:
                    print str(e)

                # 更新主程序
                res = server_update(client, sftp, customer_pack, serverpackage.machine, stringIO, "/home/rzrk/update/", "auto_deploy_server_%s_install.tar.gz" % datetime.datetime.now().strftime("%Y%m%d"))

                if not res['success']:
                    client.close()
                    return HttpResponse(json.dumps(str(res)), mimetype="application/json")
                else:
                    res_list.append(res)
                    deployINFO = "server更新成功"
                    deployPercent = 60


                # 更新portal
                try:
                    res = portal_update(client, sftp, customer_pack.customer, machine, portalIO, "/home/rzrk/update/", "auto_deploy_portal_%s_%s.tar.gz" % (datetime.datetime.now().strftime("%Y%m%d"), portal_package.svn_version))
                except Exception as e:
                    print str(e)
                if not res['success']:
                    client.close()
                    return HttpResponse(json.dumps(str(res)), mimetype="application/json")
                else:
                    res_list.append(res)
                    deployINFO = "portal更新成功"
                    deployPercent = 75

                # 更新mysql
                if serverpackage == customer_pack.machine_packages[0]:
                    if len(customer_pack.portal_upgrade_sql) > 0:
                        sqlIO = StringIO(customer_pack.portal_upgrade_sql)
                        sqlPath = "/home/rzrk/update/%s.sql" % datetime.datetime.now().strftime("%Y%m%d")
                        sftp.putfo(sqlIO, sqlPath)
                        cmd = '/usr/bin/python /home/rzrk/update/_update/Deploy.py %s' % sqlPath
                        logger.info("excute %s" % cmd)
                        stdin, stdout, stderr = client.exec_command(cmd)
                        out = stdout.readlines()
                        err_list = stderr.readlines()
                        if len(err_list) > 0:
                            logger.info('[%s excuete sql error %s] ' % (customer_pack.customer.name, "\n".join(err_list)))
                        else:
                            logger.info('[%s excuete sql %s] ' % (customer_pack.customer.name, "\n".join(out)))
                            deployINFO = "数据库更新成功"
                            deployPercent = 90
                client.close()
                sftp.close()

                logger.info('[%s] end of auto deploy machine %s by user %s' % (customer_pack.customer.name, serverpackage.machine.name, request.user.username))

                # 增加升级记录

                deployRecord = DeployRecord()
                deployRecord.customer = serverpackage.customer
                deployRecord.machine = serverpackage.machine
                deployRecord.new_version = serverpackage
                deployRecord.portal_package = portal_package
                deployRecord.portal_upgrade_sql = customer_pack.portal_upgrade_sql
                deployRecord.start_time = startTime
                deployRecord.end_time = datetime.datetime.now()
                deployRecord.deploy_user = request.user.username
                deployRecord.remark = "auto deploy"
                deployRecord.create_time = datetime.datetime.now()
                deployRecord.create_user = request.user
                deployRecord.generatorJson = ""

                deployRecord.save()

                logger.info('[%s] added machine %s deploy record by user %s' % (customer_pack.customer.name, serverpackage.machine.name, request.user.username))
                deployINFO = "升级记录已添加"
                deployPercent = 95

            customerDeployRecord = CustomerDeployRecord()
            customerDeployRecord.customer = customer_pack.customer
            customerDeployRecord.cus_package = customer_pack
            customerDeployRecord.portal_upgrade_sql = customer_pack.portal_upgrade_sql
            customerDeployRecord.start_time = customerStartTime
            customerDeployRecord.end_time = datetime.datetime.now()
            customerDeployRecord.deploy_user = request.user.username
            customerDeployRecord.remark = "auto deploy"
            customerDeployRecord.create_time = datetime.datetime.now()
            customerDeployRecord.create_user = request.user
            customerDeployRecord.save()
            print "deploy Record success!"
            logger.info('[%s] added customer deploy record by user %s' % (customer_pack.customer.name, request.user.username))

            response['success'] = True
            response['error'] = '部署成功'
            deployINFO = "部署完成"
            deployPercent = 100

        else:
            response['error'] = '需要手动部署'


    return HttpResponse(json.dumps(response), mimetype="application/json")


#更新进度查询
def deployProcessInfo(request):
    global deployINFO
    global deployPercent
    if request.method == "GET":
        response = {"success": True, "deployINFO": deployINFO, "deployPercent": deployPercent}
        return HttpResponse(json.dumps(response), mimetype="application/json")


#生成客户包
def customerpackage_create(customer,install_package_list,portal_package,portal_upgrade_sql,user,remark):
    global deployINFO
    deployINFO = "正在生成客户包"
    customer_package = CustomerPackage()
    customer_package.name = "%s_%s" % (customer.name, datetime.datetime.now().strftime("%Y%m%d"))
    customer_package.is_enabled = True
    customer_package.customer = customer
    customer_package.machines = customer.machines
    customer_package.machine_packages = install_package_list
    customer_package.portal_package = portal_package
    customer_package.portal_upgrade_sql = portal_upgrade_sql
    customer_package.create_time = datetime.datetime.now()
    customer_package.create_user = user
    customer_package.remark = remark
    customer_package.save()
    return customer_package


@csrf_exempt
@login_required
def check_sql(request):
    response = {"success": False, "error": ""}
    if request.method == "POST":
         #判断是否需要升级脚本
        start_time = datetime.datetime.now()
        sql_script_file_name = start_time.strftime('%Y_%m_%d_%H_%M_%S_%f') + '_sql'

        # 执行登陆操作
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(PORTAL_GET_SQL_IP, PORTAL_GET_SQL_PORT, PORTAL_GET_SQL_USERNAME, PORTAL_GET_SQL_PASSWORD, timeout=5)

        # 准备路径
        stdin, stdout, stderr = ssh.exec_command('mkdir /deploy_portal_gen_sql/')
        stdin, stdout, stderr = ssh.exec_command('mkdir /deploy_portal_gen_sql/%s/' % sql_script_file_name)
        sql_script_file_path = '/deploy_portal_gen_sql/%s/old.sql' % sql_script_file_name
        sftp = ssh.open_sftp()
        #导出数据库

        stdin, stdout, stderr = ssh.exec_command('mysqldump --no-data -uroot -pmysql.rzrk ttmgrportal > %s' % sql_script_file_path)
        time.sleep(5)
        try:
            #stdin, stdout, stderr = ssh.exec_command('/bin/cat %s' % sql_script_file_path)
            local_script_file_path = '/home/rzrk/portal_%s' % sql_script_file_name
            if os.path.exists(local_script_file_path):
                os.system('rm -rf %s' % local_script_file_path)

            sftp.get(sql_script_file_path, local_script_file_path)
            if not os.path.exists(local_script_file_path):
                print 'FILE %s does not exist' % local_script_file_path

        except Exception as e:
            response['error'] = str(e)
            return HttpResponse(json.dumps(response), mimetype="application/json")

        file_obj = open(local_script_file_path, 'r')
        pp_old_sql_read = file_obj.read()
        file_obj.close()

        pp_old = PortalPackage()
        pp_old.svn_version = 'unknown'
        pp_new = PortalPackage.objects(is_enabled=True).order_by('-update_time')
        pp_new = pp_new[0]
        pp_new_sql_read = pp_new.sql.read()

        #比较文件是否相同
        if pp_old_sql_read == pp_new_sql_read:
            response["success"] = True
            response["error"] = "建库脚本无变动!无须升级!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        # 准备新的建库脚本
        new_file_path = os.path.join(TEMP_ROOT, "new.sql")
        new_file = open(new_file_path, 'w')
        new_file.write(pp_new_sql_read)

        new_file.close()
        # 上传到服务器,你截图那个没指定文件名吧？
        sftp.put(new_file_path, '/deploy_portal_gen_sql/%s/new.sql' % sql_script_file_name)
        #登陆数据库
        db = MySQLdb.connect(host=PORTAL_GET_SQL_IP, user=PORTAL_GET_SQL_SQL_NAME, passwd=PORTAL_GET_SQL_SQL_PWD)
        cursor = db.cursor()
        sql = [
                'drop database if exists ttmgrportal_old',
                'drop database if exists ttmgrportal_new',
                'create database ttmgrportal_old',
                'create database ttmgrportal_new'
            ]
        for item_sql in sql:
            cursor.execute(item_sql)
        db.close()

        # 导入数据库
        stdin, stdout, stderr = ssh.exec_command('mysql -uroot -pmysql.rzrk ttmgrportal_new < /deploy_portal_gen_sql/%s/new.sql' % sql_script_file_name)
        stdout.read()
        stdin, stdout, stderr = ssh.exec_command('mysql -uroot -pmysql.rzrk ttmgrportal_old < /deploy_portal_gen_sql/%s/old.sql' % sql_script_file_name)
        stdout.read()

        #执行比较语句
        stdin, stdout, stderr = ssh.exec_command('schemasync -r --output-dir="/deploy_portal_gen_sql/%s/" mysql://%s:%s@%s:3306/ttmgrportal_new  mysql://%s:%s@%s:3306/ttmgrportal_old' %
                                                     (sql_script_file_name, PORTAL_GET_SQL_SQL_NAME, PORTAL_GET_SQL_SQL_PWD, PORTAL_GET_SQL_IP, PORTAL_GET_SQL_SQL_NAME, PORTAL_GET_SQL_SQL_PWD, PORTAL_GET_SQL_IP)
            )


        # 将文件获取到本地
        patch_flag = False

        patch_file_path = '/deploy_portal_gen_sql/%s/ttmgrportal_old.%s.patch.sql' % (sql_script_file_name, start_time.strftime('%Y%m%d'))
        local_patch_file_path = os.path.join(TEMP_ROOT, "portal_%s_to_%s.sql" % (pp_old.svn_version, pp_new.svn_version))
        try:
            sftp.get(patch_file_path, local_patch_file_path)
            patch_flag = True
        except Exception as e:
            logger.error('执行比较脚本异常! --> ' + getTraceBack())

        # 删除生成的路径
        stdin, stdout, stderr = ssh.exec_command('rm -r /deploy_portal_gen_sql/*')
        #stdout.read()


        # 结束时间毫秒数
        end_milliseconds = time.time()

        # 解析建库脚本,及生成的比较语句,生成最终的建库脚本
        # 结束时间
        end_time = datetime.datetime.fromtimestamp(end_milliseconds)
        # 以结束时间作为版本号
        upgrade_version = VERSION_PREFIX_PORTAL_UPGRADE_SCRIPT + str(int(end_milliseconds * 1000))

        # 提取出需要的数据

        add_sql = get_add_sql(new_file_path)

        local_patch_file_final_path = os.path.join(TEMP_ROOT, "portal_%s_to_%s_final.sql" % (pp_old.svn_version, pp_new.svn_version))
        local_patch_file_final = open(local_patch_file_final_path, 'w')

        local_patch_file_final.write('\r\n')
        local_patch_file_final.write('\r\n')
        local_patch_file_final.write('-- --------------------------------------------------------' + '\r\n')
        local_patch_file_final.write('-- Portal upgrade script' + '\r\n')
        local_patch_file_final.write('-- script version: %s' % upgrade_version + '\r\n')
        local_patch_file_final.write('-- from   version: %s' % pp_old.svn_version + '\r\n')
        local_patch_file_final.write('-- to     version: %s' % pp_new.svn_version + '\r\n')
        local_patch_file_final.write('-- create by     : %s' % User.objects.get(pk=request.user.id).username + '\r\n')
        local_patch_file_final.write('-- start  time   : %s' % start_time.strftime('%Y-%m-%d %H:%M:%S.%f') + '\r\n')
        local_patch_file_final.write('-- end    time   : %s' % end_time.strftime('%Y-%m-%d %H:%M:%S.%f') + '\r\n')
        local_patch_file_final.write('-- power  by     : tt_engine' + '\r\n')
        local_patch_file_final.write('-- --------------------------------------------------------' + '\r\n')
        local_patch_file_final.write('\r\n')
        local_patch_file_final.write('\r\n')
        local_patch_file_final.write('SET FOREIGN_KEY_CHECKS=0;' + '\r\n')


        # 生成patch成功
        if patch_flag:
            with open(local_patch_file_path) as local_patch_file:
                for line in local_patch_file:
                    if line.startswith('--') or not line.strip():
                        continue
                    if line.lower().strip().startswith('use'):
                        continue
                    local_patch_file_final.write(line + '\r\n')

        # 添加额外的SQL语句
        for key in add_sql:
            value = add_sql[key]
            local_patch_file_final.write('-- --------------------------------------------------------' + '\r\n')
            local_patch_file_final.write('-- init table %s' % key + '\r\n')
            local_patch_file_final.write('-- --------------------------------------------------------' + '\r\n')
            for item_sql in value:
                local_patch_file_final.write(item_sql)

        local_patch_file_final.write('SET FOREIGN_KEY_CHECKS=1;' + '\r\n')
        local_patch_file_final.flush()
        local_patch_file_final.close()


        # 上传到服务器上
        sftp.put(local_patch_file_final_path,'/home/rzrk/update/portal_%s_to_%s_final.sql'% (pp_old.svn_version, pp_new.svn_version))
        #导入数据库
        stdin, stdout, stderr = ssh.exec_command('mysql -uroot -pmysql.rzrk ttmgrportal < /home/rzrk/update')
        time.sleep(5)
        ssh.close()

        response["success"] = True
        response["error"] = '更新数据库成功'
    else:
        error = '请使用http-post方式请求'
        logger.error(error)

    return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")




def get_add_sql(new_file_path):
    """
    获取需要额外添加的SQL语句
    :param new_file_path:
    :return:
    """
    add_sql = {item: [] for item in PORTAL_GEN_SQL_ADD_TABLE}

    match_str = None
    is_not_end = False
    with open(new_file_path) as new_file:
        for line in new_file:
            # 过滤掉注释行
            if line.startswith('--'):
                continue
            if is_not_end:
                add_sql[match_str].append(line)
                if line.strip().endswith(';'):
                    is_not_end = False
                continue

            # 是否匹配
            flag, str = match_sql_key(line)

            if not flag:
                continue
            # 排除一些索引的情况
            if not line.lower().strip().startswith('create table') and not line.lower().strip().startswith('insert into') and not line.lower().strip().startswith('drop table'):
                continue
            # 添加到SQL集
            add_sql[str].append(line)
            if not line.strip().endswith(';'):
                is_not_end = True
                match_str = str
    return add_sql

def match_sql_key(line):
    for item in PORTAL_GEN_SQL_ADD_TABLE:
        m = re.match(r'^.*`%s`.*$' % item, line)
        if m:
            return True, item
    return False, None



@csrf_exempt
@login_required
def compiling_list(request):
    """
    查看编译机状态
    :param request:
    :return:
    """
    if request.method == "GET":
        # 查询编译机
        machine_json = []
        machines = Machine.objects(type=1)
        for machine in machines:
            machine_json_item = {'machine': None, 'record': None}
            # 机器
            machine_json_item['machine'] = convert_machine_to_json(machine)

            # 查询编译机最后一条日志
            compiling_record = CompilingUpdateRecord.objects(machine=machine).order_by('-start_time')
            if len(compiling_record) > 0:
                compiling_record = compiling_record[0]
                machine_json_item['record'] = convert_compiling_record_to_json(compiling_record)
            else:
                compiling_record = None
                machine_json_item['record'] = None
            machine_json.append(machine_json_item)

        machine_json = json.dumps(machine_json)
        return render_to_response("customer/customer_view.html", locals(), context_instance=RequestContext(request))
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def compiling_record_list(request):
    """
    查看编译机日志
    :param request:
    :return:
    """
    if request.method == "GET":
        records = CompilingUpdateRecord.objects().order_by("-start_time")
        return render_to_response("customer/customer_compile_record_list.html", locals(), context_instance=RequestContext(request))
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def compiling_record_del(request):
    response = {"success": False, "error": ""}
    try:
        # 校验参数
        id = request.POST.get("id", None)

        if id is None or str(id).strip() == "":
            response["error"] = "必要参数为空!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        # 执行删除操作
        record = CompilingUpdateRecord.objects(pk=id)
        if len(record) == 0:
            response["error"] = "未找到该记录!"
            return HttpResponse(json.dumps(response), mimetype="application/json")

        record = record[0]
        record.delete()
        response["success"] = True
        response["error"] = "执行成功!"
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception, e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")

@csrf_exempt
@login_required
def client_package_download(request):
    try:
        file_info_id = request.GET.get('id', None)
        if file_info_id is None or file_info_id == '':
            error = "必要参数为空"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        # 验证对象是否存在
        files = FileInfoDetail.objects(pk=file_info_id)
        if len(files) == 0:
            error = '未找到文件对象'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        file = files[0]
        if not file.file:
            error = '该文件对象无文件'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        filename = file.filePath
        arr = filename.split("\\")
        filename = arr[len(arr)-1]
        content = file.file.read()
        response = HttpResponse(content, mimetype='application/octet-stream|exe')
        response['Content-Length'] = len(content)
        response['Content-Disposition'] = 'attachment; filename=%s' % filename.encode('utf-8')
        return response
    except Exception as e:
        error = '下载文件异常[%s]' % str(e)
        logger.error(error + getTraceBack())
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def client_compiling(request):
    """
    编译升级
    :param request:
    :return:
    """
    if request.method == "GET":
        # 获取参数
        # 机器ID
        cus_id = request.GET.get('cus_id', None)
        if cus_id is None:
            error = '重要参数不能为空!'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer = Customer.objects(pk=cus_id)
        if len(customer) == 0:
            error = '客户[id=%s]并不存在!' % cus_id
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 客户
        customer = customer[0]
        # 客户的模块
        modules = customer.modules
        # 编译所需参数
        module_file_raw_path = {}
        # 查找编译机
        machines = Machine.objects(type=1, os=OS_TYPE_WINDOWNS)

        if modules is None or len(modules) == 0:
            error = '客户[id=%s][name=%s]无任何模块无法编译!' % (cus_id, customer.name)
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 记录所有模块参数名
        program_names = [UPDATER, DEAMON, QUOTER, XT_TRADE_CLIENT]
        clientInfo = ClientDefaultBranch.objects(customer=customer)
        branchInfos = BranchInfo.objects().order_by("-branchTag")
        return render_to_response("customer/customer_client_compile.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        response = {"success": False, "error": ""}
        try:
            # 获取参数
            req_json = request.POST.get('json', None)
            req_json = json.loads(req_json)

            cus_id = req_json['cus_id']
            machine_id = req_json['machine_id']
            updates = req_json['updates']
            compiles = req_json['compiles']
            cleans = req_json['cleans']
            remark = req_json['remark']
            quoter_settings = (req_json['quoter_settings']).strip()
            is_package = req_json['is_package']
            all_branch = req_json['all']

            # 客户信息
            customer = Customer.objects(pk=cus_id)
            if len(customer) == 0:
                response["error"] = "未能获取此客户[id=%s]" % cus_id
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = customer[0]

            # 确认指定机器是否处于待编译状态
            machine = Machine.objects.get(pk=machine_id)

            if machine.type != 1:
                response["error"] = "不能对非编译机下达指令!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            # 查询编译日志,找到最新一条记录
            compiling_record = CompilingUpdateRecord.objects(machine=machine).order_by('-start_time')
            if len(compiling_record) > 0:
                compiling_record = compiling_record[0]
                if compiling_record.status not in [4, 5]:
                    response["error"] = "本机正在执行操作,请等候!"
                    return HttpResponse(json.dumps(response), mimetype="application/json")

            startTime = datetime.datetime.now()
            xt_trade_client_branch = BranchInfo.objects.get(pk=all_branch[3])

            op = Operation.Operation(customer, xt_trade_client_branch, remark)
            res = op.checkSettings()
            if not res['success']:
                return HttpResponse(json.dumps(res), mimetype="application/json")

            # 开始执行操作
            # update
            for item in updates:
                branch = BranchInfo.objects.get(pk=item)
                response = op.updateSvn(branch)
                if not response['success']:
                    return HttpResponse(json.dumps(response), mimetype="application/json")
            # clean
            for item in cleans:
                branch = BranchInfo.objects.get(pk=item)
                response = op.cleanSolution(branch)
                if not response['success']:
                    return HttpResponse(json.dumps(response), mimetype="application/json")
            # compiles
            for item in compiles:
                branch = BranchInfo.objects.get(pk=item)
                response = op.buildSolution(branch)
                if not response['success']:
                    return HttpResponse(json.dumps(response), mimetype="application/json")

            if is_package:
                response = op.makePackage(quoter_settings)
                if not response['success']:
                    return HttpResponse(json.dumps(response), mimetype="application/json")
                else:
                    file_path = response['error']
                    if os.path.exists(file_path):
                        fInfo = os.stat(file_path)
                        size = fInfo.st_size
                        sha1 = hashlib.sha1(open(file_path).read()).hexdigest()
                        details = FileInfoDetail.objects(sha1=sha1, size=size, filePath=file_path)
                        detail = None
                        if len(details) > 0:
                            detail = details[0]
                            if len(detail.svnVersion) == 0:
                                detail.svnVersion = getSvnInfo(file_path)
                        else:
                            detail = FileInfoDetail()
                            detail.filePath = file_path
                            #detail.info = file
                            detail.createTime = datetime.datetime.fromtimestamp(fInfo.st_ctime)
                            detail.updateTime = datetime.datetime.fromtimestamp(fInfo.st_mtime)
                            detail.size = fInfo.st_size
                            detail.sha1 = hashlib.sha1(open(file_path, 'rb').read()).hexdigest()
                            #detail.svnVersion = 'None'
                            f = open(file_path, "rb")
                            detail.file.put(f)
                            f.close()
                            detail.save()

                branchMap = dict()  # to write into mongodb
                branches = list() # to write into mongodb
                for branch_info_id in all_branch:
                    branch = BranchInfo.objects.get(pk=branch_info_id)
                    branchMap[branch.programName] = getLocalDir(branch.programName) + "/" + branch.branchTag
                    branches.append(branch)

                client_package = ClientPackage()
                client_package.version = op.get_version()
                client_package.customer = customer
                client_package.machine = machine
                client_package.start_time = startTime
                client_package.end_time = datetime.datetime.now()
                client_package.create_user = request.user
                client_package.branches = branches
                client_package.file = detail
                client_package.svn_info = generator_svn_info(branchMap)
                client_package.remark = remark
                client_package.save()

                response['error'] = str(detail.id)

            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception, e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")

def addCommonPackageInfo(lastPackage, package, writeTar):
    # 加入updateInfo.json和前一次的安装json
    lastInfos = {}
    lastInfos["fileInfos"] = {}
    lastInfos["xtDir"] = package.machine.xtDir
    if lastPackage is not None:
        for detail in lastPackage.files:
            if type(detail) == type(FileInfoDetail()):
                lastInfos["fileInfos"][detail.filePath] = detail.toDict()
    jsonInfo = json.dumps(lastInfos, indent=4)
    jsonInfo = replaceStr(jsonInfo, {"xtDir": package.machine.xtDir})
    addfilefromstring(writeTar, "lastUpdate.json", jsonInfo)

    # updateInfo
    infos = {}
    infos["fileInfos"] = {}
    # 写入产生信息
    infos["xtDir"] = package.machine.xtDir
    infos["packageName"] = package.version
    infos["branches"] = package.branches
    for detail in package.files:
        infos["fileInfos"][detail.filePath] = detail.toDict()
    jsonInfo = json.dumps(infos, indent=4)
    jsonInfo = replaceStr(jsonInfo, {"xtDir": package.machine.xtDir})
    addfilefromstring(writeTar, "update.json", jsonInfo)

    localDir = os.path.dirname(os.path.abspath(__file__))
    files = ["update.sh","win_update.bat", "Deploy.py", "win_Deploy.py","README","y.txt","MasterRun.py","new.txt","old.txt"]
    for file in files:
        path = localDir + "/../deploy/" + file
        fOri = open(path,'r')
        data = fOri.read()
        fOri.close()
        #处理文件
        data = data.replace('{{xtDir}}', package.machine.xtDir)
        #保存新的内容
        fNew = open(path,'w')
        fNew.write(data)
        fNew.close()
        addfile(writeTar, file, path)


@csrf_exempt
@login_required
def package_list(request):
    cus_id = request.GET.get("cus_id", None)
    customer = Customer.objects.get(pk=cus_id)

    machines = customer.machines

    if not machines:
        error = '请先为客户添加机器'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

    packages = InstallPackage.objects().filter(machine__in=machines).order_by("-create_time")

    return render_to_response("customer/customer_package_list.html", locals())


@csrf_exempt
@login_required
def deploy_package_list(request):
          id=request.GET.get('cus_id',None)
          customer=Customer.objects.get(pk=id)
          packages=DeployRecord.objects(customer=customer).order_by("-start_time")
          return render_to_response("customer/customer_deploy_package_list.html", locals())


@csrf_exempt
@login_required
def package_view(request):
    package_id = request.GET.get("package_id", None)

    if not package_id:
        error = '必要参数为空!'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

    package = InstallPackage.objects.get(pk=package_id)

    customer = package.customer

    return render_to_response("customer/customer_package_view.html", locals())


@csrf_exempt
@login_required
def package_cus(request, cus_id=None):
    if not cus_id:
        error = '必要参数为空!'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

    customer = Customer.objects.get(pk=cus_id)

    packages = CustomerPackage.objects(customer=customer).order_by("-create_time")

    return render_to_response("customer/customer_package.html", locals())


@csrf_exempt
@login_required
def package_branch(request):
    if request.method == 'GET':
        response = {'success': False, 'error': ''}
        try:
            # 获取参数
            packageId = request.GET.get('packageId', None)

            if not packageId:
                response["error"] = "必要参数为空!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            package = InstallPackage.objects(pk=packageId)

            if len(package) == 0:
                response["error"] = "未获取到该对象!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            package = package[0]
            svn_info = package.svn_info
            svn_info = {} if not svn_info else json.loads(svn_info)

            branches = None
            if svn_info:
                branches = [[item, svn_info[item][1]] for item in svn_info]
            else:
                branches = [[item, '-'] for item in package.branches.split(',')]

            response['data'] = {'id': str(package.id), 'branches': branches}
            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def package_file(request):
    if request.method == 'POST':
        error = '请使用http-get方式请求'
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    elif request.method == 'GET':
        response = {'success': False, 'error': ''}
        try:
            # 获取参数
            packageId = request.GET.get('packageId', None)
            if not packageId:
                response["error"] = "必要参数为空!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            package = InstallPackage.objects(pk=packageId)

            if len(package) == 0:
                response["error"] = "未获取到该对象!"
                return HttpResponse(json.dumps(response), mimetype="application/json")

            package = package[0]
            files = package.files
            file_json = []

            for file in files:
                # TODO
                if isinstance(file, DBRef):
                    continue
                info = file.toDict()
                info["id"] = str(file.id)
                file_json.append(info)

            response['data'] = file_json
            response["success"] = True
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response, ensure_ascii=True), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def package_file_download(request):
    """
    下载文件
    :param request:
    :return:
    """
    try:
        # 获取参数
        id = request.GET.get('id', None)

        if id is None or id == '':
            error = "必要参数为空!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 验证对象是否存在
        file = FileInfoDetail.objects(pk=id)

        if len(file) == 0:
            error = "未找到对应文件!"
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        file = file[0]
        file_name = file.filePath.split('/')[len(file.filePath.split('/')) - 1]

        content = file.file.read()
        size = file.size
        response = HttpResponse(content)
        response['Content-Length'] = size
        response['Content-Disposition'] = 'attachment; filename=%s' % file_name
        return response
    except Exception as e:
        error = "下载文件异常![%s]" % str(e)
        logger.error(error + getTraceBack())
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def package_file_read(request):
    """
    查看文件
    :param request:
    :return:
    """
    if request.method == 'GET':
        try:
            # 获取参数
            id = request.GET.get('id', None)
            if id is None or id == '':
                data = "必要参数为空！"
                logger.error(data)
                return render_to_response('customer/include/customer_package_file_read.html', locals(), context_instance=RequestContext(request))
            # 验证对象是否存在
            file = FileInfoDetail.objects(pk=id)

            if len(file) == 0:
                error = '未找到对应文件！'
                logger.error(error)
                return render_to_response('customer/include/customer_package_file_read.html', locals(), context_instance=RequestContext(request))

            file = file[0]
            file_name = file.filePath.split('/')[len(file.filePath.split('/')) - 1]

            content = file.file.read()
            head = file_name
            data = content.decode('gbk')

            return render_to_response('customer/include/customer_package_file_read.html', locals(), context_instance=RequestContext(request))
        except Exception as e:
            data = "加载文件异常![%s]" % str(e)
            return render_to_response('customer/include/customer_package_file_read.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def package_del(request):
    response = {'success': False, 'error': ''}
    try:
        id = request.POST.get("id")
        package = InstallPackage.objects.get(pk=id)

        if len(DeployRecord.objects(new_version=package)) > 0:
            response['error'] = '不能删除已使用的安装包!'
            return HttpResponse(json.dumps(response), mimetype="application/json")

        if package is not None:
            package.delete()
        response['success'] = True
        response['error'] = '执行成功!'
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception as e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def cus_package_del(request):
    response = {'success': False, 'error': ''}
    try:
        id = request.POST.get("id")
        package = CustomerPackage.objects.get(pk=id)

        if len(CustomerDeployRecord.objects(cus_package=package)) > 0:
            response['error'] = '不能删除已使用的客户包!'
            return HttpResponse(json.dumps(response), mimetype="application/json")

        if package is not None:
            package.delete()
        response['success'] = True
        response['error'] = '执行成功!'
        return HttpResponse(json.dumps(response), mimetype="application/json")
    except Exception as e:
        response["error"] = "系统异常![%s]" % str(e)
        logger.error(response["error"] + getTraceBack())
        return HttpResponse(json.dumps(response), mimetype="application/json")


@login_required
def download_install_package(request):
    """
    下载安装包
    :param request:
    :return:
    """
    if True:
        id = request.GET.get("packageId")
        package = InstallPackage.objects.get(pk=id)
        if package is None:
            error = "未找到安装包"
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        lastPackage = None
        record = DeployRecord.objects(machine=package.machine).order_by("-start_time")
        if len(record) > 0:
            lastPackage = record[0].new_version

        if type(lastPackage) == DBRef:
            error = '最新升级记录的安装包已被删除!'
            logger.error(error)
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        stringIO = StringIO()
        writeTar = tarfile.open(fileobj=stringIO, mode="w:gz")

        logger.info("add common info ")
        addCommonPackageInfo(lastPackage, package, writeTar)

        for file in package.files:
            logger.info("add file[%s]" % file.filePath)
            content = file.file.read()
            if content is not None:
                strIO = StringIO(content)
                info = tarfile.TarInfo(file.filePath)
                info.mode = file.info.mod
                info.size = len(content)
                info.mtime = time.time()
                writeTar.addfile(info, strIO)
            else:
                logger.info("find path error %s" % file.filePath)

        writeTar.close()
        content = stringIO.getvalue()
        size = len(content)
        # 发送包
        response = HttpResponse(content)
        response['Content-Length'] = size
        response['Content-Disposition'] = 'attachment; filename="%s_%s_%s_install.tar.gz"' % (package.customer.tag, package.machine.name, datetime.datetime.now().strftime("%Y%m%d"))
        return response


def gen_update_package(package):
    stringIO = StringIO()

    lastPackage = None
    record = DeployRecord.objects(machine=package.machine).order_by("-start_time")
    if len(record) > 0:
        lastPackage = record[0].new_version

    writeTar = tarfile.open(fileobj=stringIO, mode="w:gz")
    addCommonPackageInfo(lastPackage, package, writeTar)

    lastFileMap = {}
    if lastPackage is not None:
        for file in lastPackage.files:
            if type(file) == type(FileInfoDetail()):
                lastFileMap[file.filePath] = file

    # 与前一个包比较
    for file in package.files:
        rawFile = lastFileMap.get(file.filePath, None)
        if rawFile is None or rawFile.sha1 != file.sha1 or rawFile.size != file.size:
            content = file.file.read()
            strIO = StringIO(content)
            info = tarfile.TarInfo(file.filePath)
            info.mode = file.info.mod
            info.size = len(content)
            info.mtime = time.time()
            writeTar.addfile(info, strIO)
            logger.info('add file %s' % file.filePath)

    writeTar.close()
    return stringIO.getvalue()

# 下载升级包
@csrf_exempt
@login_required
def download_update_package(request):
    id = request.GET.get("packageId")
    package = InstallPackage.objects.get(pk=id)
    if package is None:
        error = "未找到安装包"
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

    stringIO = StringIO(gen_update_package(package))
    content = stringIO.getvalue()
    size = len(content)

    # 发送包
    response = HttpResponse(content)
    response['Content-Length'] = size
    response['Content-Disposition'] = 'attachment; filename="%s_%s_%s_update.tar.gz"' % (package.customer.tag, package.machine.name, datetime.datetime.now().strftime("%Y%m%d"))
    return response


@csrf_exempt
@login_required
def package_create(request):
    if request.method == "GET":
        customerId = request.GET.get("cus_id", None)
        customer = Customer.objects(pk=customerId)
        customer = customer[0]
        machines = customer.machines

        if not machines:
            error = '客户无机器!'
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        #记录所有模块参数名
        customerDeployStatus = CustomerDeployStatus.objects(customer=customer).order_by('-create_time')
        if len(customerDeployStatus) > 0:
            customerDeployStatus = customerDeployStatus[0]
            svnINFO = customerDeployStatus.server_svn_info
            if len(svnINFO) > 0:
                server_current_version = svnINFO[0]['server_current_revision']
                server_previous_version = svnINFO[0]['server_previous_revision']
        program_names = [TT_SERVICE, BROKER, QUOTER, CLEARSERVICE, CTPSERVICE, APISERVICE]
        defaultInfo = CustomerDefaultBranch.objects(customer=customer)
        branchInfos = BranchInfo.objects(programName__in=program_names).order_by("-branchTag")
        return render_to_response("customer/customer_package_create.html", locals())
    else:
        response = {'success': False, 'error': ''}
        try:
            json_str = request.POST.get("json", None)
            json_obj = json.loads(json_str)

            customerId = json_obj["customerId"]
            machine_id_list = json_obj["machine_id_list"]
            branchMap = json_obj["params"]
            remark = json_obj["remark"]
            updateMode = json_obj["updateMode"]
            srcVersion = json_obj["srcVersion"]
            dstVersion = json_obj["dstVersion"]
            selfDefine = json_obj["selfDefine"]

            FILEPATH = "/home/ftpuser/linux_soft/soft/updateSQL.sh"
            # FILEPATH = "E:/home/updateSQL.sh"
            if selfDefine == "自定义参数":
                with open(FILEPATH, 'w') as f:
                    f.write("#!/bin/bash\n")
                    run_params = "/usr/bin/python /home/rzrk/server/pyScripts/mysqlUpdate/MysqlUpdate.py" + " " + updateMode + " " + srcVersion + " " + dstVersion
                    f.write(run_params)

            else:
                with open(FILEPATH, 'w') as f:
                    f.write("#!/bin/bash\n")
                    run_params = "/usr/bin/python /home/rzrk/server/pyScripts/mysqlUpdate/MysqlUpdate.py" + " " + selfDefine
                    f.write(run_params)


            if not customerId or not machine_id_list:
                response['error'] = '客户Id或者机器Id为空'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            machines = Machine.objects(pk__in=machine_id_list)

            if len(machines) != len(machine_id_list):
                response['error'] = '未能获取全部机器!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects(pk=customerId)

            if customer is None:
                response['error'] = '未找到客户!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = customer[0]
            user = User.objects.get(pk=request.user.id)

            flag = True
            error_info = ''

            # make a UUID based on the host ID and current time
            base_uuid = str(uuid.uuid1())
            now = datetime.datetime.now()
            install_package_list = []

            # 开始生成程序包
            for machine in machines:
                one_flag, error_info_item, install_package = generator_cus_machine_package(customer, machine, branchMap, user, remark)
                if not one_flag:
                    flag = False
                else:
                    install_package_list.append(install_package)
                error_info += '\n\n'
                error_info += '<br>'
                error_info += error_info_item

            # 设置必要属性,保存Server包对象
            if flag:
                for install_package_item in install_package_list:
                    install_package_item.create_time = now
                    install_package_item.group_key = base_uuid
                    install_package_item.save()

            response['success'] = flag
            response['error'] = error_info
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")

           


@csrf_exempt
@login_required
def cus_package_create(request):
    if request.method == "GET":
        cus_id = request.GET.get("cus_id", None)
        customer = Customer.objects.get(pk=cus_id)
        machines = customer.machines

        if not machines:
            error = '客户无机器!'
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        # 获取所有可用PortalPackage
        portal_packages = PortalPackage.objects(is_enabled=True).order_by('svn_url', '-svn_version')

        # 获取所有可用ServerPackage
        install_packages = InstallPackage.objects(is_enabled=True, customer=customer, group_key__ne=None).order_by('-create_time')

        install_package_page = []
        last_group_key = None
        for install_package in install_packages:
            this_group_key = install_package.group_key
            # 相等则添加到最后一列
            if this_group_key == last_group_key:
                install_package_page[len(install_package_page) - 1].append(install_package)
            else:
                install_package_page.append([install_package])
            last_group_key = this_group_key

        return render_to_response("customer/customer_cus_package_create.html", locals())
    else:
        response = {'success': False, 'error': ''}
        try:
            json_str = request.POST.get("json", None)
            json_obj = json.loads(json_str)

            cus_id = json_obj["cus_id"]
            server_package_id_arr = json_obj["server_package"]
            portal_package_id = json_obj["portal_package"]
            remark = json_obj["remark"]
            portal_upgrade_sql = json_obj.get('portal_upgrade_sql', None)

            # 客户参数
            customer = Customer.objects(pk=cus_id)

            if customer is None:
                response['error'] = '未找到客户!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = customer[0]

            # Portal包
            portal_package = PortalPackage.objects(pk=portal_package_id)

            if not portal_package:
                response['error'] = '未找到对应Portal包!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            portal_package = portal_package[0]

            # Server包
            server_packages = InstallPackage.objects(pk__in=server_package_id_arr)

            if not server_packages:
                response['error'] = '未找到对应Server包!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            user = User.objects.get(pk=request.user.id)

            customer_package = CustomerPackage()
            customer_package.name = "%s_%s" % (customer.name, datetime.datetime.now().strftime("%Y%m%d"))
            customer_package.is_enabled = True
            customer_package.customer = customer
            customer_package.machines = customer.machines
            customer_package.machine_packages = server_packages
            customer_package.portal_package = portal_package
            customer_package.portal_upgrade_sql = portal_upgrade_sql
            customer_package.create_time = datetime.datetime.now()
            customer_package.create_user = user
            customer_package.remark = remark
            customer_package.save()

            response['success'] = True
            response['error'] = '执行成功!'
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def cus_package_edit(request):
    if request.method == "GET":
        is_edit = True
        cus_package_id = request.GET.get("cus_package_id", None)

        customer_package = CustomerPackage.objects(pk=cus_package_id)

        if not customer_package:
            error = '未找到客户包对象!'
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        customer_package = customer_package[0]

        customer = customer_package.customer

        machines = customer.machines

        return render_to_response("customer/customer_cus_package_create.html", locals())
    else:
        response = {'success': False, 'error': ''}
        try:
            json_str = request.POST.get("json", None)
            json_obj = json.loads(json_str)

            cus_package_id = json_obj["cus_package_id"]
            remark = json_obj["remark"]
            portal_upgrade_sql = json_obj.get('portal_upgrade_sql', None)

            package = CustomerPackage.objects(pk=cus_package_id)

            if package is None:
                response['error'] = '未获取到客户包对象[id=%s]!' % cus_package_id
                return HttpResponse(json.dumps(response), mimetype="application/json")

            package = package[0]

            package.portal_upgrade_sql = portal_upgrade_sql
            package.remark = remark
            package.save()

            response['success'] = True
            response['error'] = '执行成功!'
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")

@csrf_exempt
@login_required
def cus_package_download(request):
    if request.method == "GET":
        cus_package_id = request.GET.get("id", None)
        customer_package = CustomerPackage.objects(pk=cus_package_id)

        logger.info('get customer package id: %s' % cus_package_id)

        if len(customer_package) == 0:
            response = {'succes': False, 'error':'未找到客户包对象!'}
            return HttpResponse(json.dumps(response), mimetype="application/json")

        customer_package = customer_package[0]

        try:
            logger.info('fetch machine package update script path')
            server_update_script_path = '%s/../deploy/update.sh' % settings.MEDIA_ROOT
            logger.info('fetch machine package list')
            machine_packages = customer_package.machine_packages
            logger.info('fetch portal upgrade_sql')
            portal_upgrade_sql = customer_package.portal_upgrade_sql
            logger.info('fetch portal upgrade package')
            portal_package = customer_package.portal_package

            stringIO = StringIO()
            writeTar = tarfile.open(fileobj=stringIO, mode='w:gz')

            info = tarfile.TarInfo(server_update_script_path)
            file = open(server_update_script_path, 'r')
            content = file.read()
            file.close()
            info.size = len(content)
            info.mtime = time.time()
            info.name = 'update.sh'
            strIO = StringIO(content)
            writeTar.addfile(info, strIO)

            portal_upgrade_sql_path = 'portal_upgrade_sql__%s.sql' % (datetime.datetime.now().strftime("%Y%m%d"))
            logger.info('add portal package upgrade sql into file %s_%s' %(customer_package.customer.name, portal_upgrade_sql_path))
            strIO = StringIO(portal_upgrade_sql)
            info = tarfile.TarInfo(portal_upgrade_sql_path)
            info.size = len(portal_upgrade_sql)
            info.mtime = time.time()
            writeTar.addfile(info, strIO)

            portal_package_name = "portal_package__%s.tar.gz" % (datetime.datetime.now().strftime("%Y%m%d"))
            logger.info('fetching portal package fileobj')
            content = portal_package.package.read()
            logger.info('----------------------------------add portal package fileobj to tar------------------')
            strIO = StringIO(content)
            info = tarfile.TarInfo(portal_package_name)
            info.size = len(content)
            info.mtime = time.time()
            writeTar.addfile(info, strIO)

            for machine_pack in machine_packages:
                host = machine_pack.machine.host
                logger.info('generating machine package')
                content = gen_update_package(machine_pack)

                file_name = 'machine_package__' + host + '__.tar.gz'
                #file_path = 'machine_packages/' + file_name
                file_path = file_name
                info = tarfile.TarInfo(file_path)
                info.size = len(content)
                info.mtime = time.time()

                strIO = StringIO(content)
                writeTar.addfile(info, strIO)
                logger.info('--------------------add machine package file %s-----------------------------' % file_name)

            writeTar.close()

            cus_package_name = 'customer_package_%s.tar.gz' % (\
                datetime.datetime.now().strftime("%Y%m%d"))
            content = stringIO.getvalue()
            size = len(content)

            response = HttpResponse(content)
            response['Content-Length'] = size
            response['Content-Disposition'] = 'attachment; filename=%s' % cus_package_name.encode('utf-8')
            return response
        except Exception as e:
            error = "下载文件异常![%s]" % str(e)
            logger.error(error + getTraceBack())
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

    else:
        error = "非法请求方式!"
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

def generator_cus_machine_package(customer, machine, rawMap, user, remark):
    branchMap = {}
    for k, v in rawMap.iteritems():
        branchMap[k] = getLocalDir(k) + "/" + v

    logger.info("check is lost file")
    # 检测是否缺失编译文件
    lostCompiles = []
    for module in machine.modules:
        if isinstance(module, DBRef):
            # 删除客户对应模块信息
            Customer.objects(modules__contains=module).update(pull__modules=module)
            # 删除机器对应模块信息
            Machine.objects(modules__contains=module).update(pull__modules=module)
            continue

        for file in module.files:
            # 判断需要删除的ID
            if isinstance(file, DBRef):
                Module.objects(files__contains=file).update(pull__files=file)
                continue
            try:
                rawPath = replaceStr(file.rawPath, branchMap)
            except Exception as e:
                 print str(e)
            #logger.info(rawPath)
            if not os.path.exists(rawPath) and file.fileType == FILE_TYPE_COMPILE:
                lostCompiles.append(file)

    if len(lostCompiles) > 0:
        return False, ("(%s[id=%s]-%s[id=%s])未找到以下编译文件:%s" % (customer.name, customer.id, machine.name, machine.id, ",".join([file.filePath for file in lostCompiles]))), None

    str = genPlatform(machine.modules)
    sha1 = hashlib.sha1(str).hexdigest()
    size = len(str)
    f = open("test.lua", "w")
    f.write(str)
    f.close()
    f1 = open("test.lua", "r")
    sha2 = hashlib.sha1(f1.read()).hexdigest()
    logger.info(sha1 == sha2)

    logger.info("add module files")
    fileDetails = []
    # 模块文件
    logger.info('[generator_cus_machine_package] machine id: %s, machine name: %s, machine type: %s' % (machine.id, machine.name, machine.type))
    logger.info('[generator_cus_machine_package] num of modules: %s' % len(machine.modules))
    for module in machine.modules:
        logger.info('[generator_cus_machine_package] module name: %s, file num: %s' % (module.name, len(module.files)))
        for file in module.files:
            rawPath = replaceStr(file.rawPath, branchMap)
            logger.info('[generator_cus_machine_package] file path: %s' % rawPath)
            if os.path.exists(rawPath):
                filePath = replaceStr(file.filePath, branchMap)
                fInfo = os.stat(rawPath)
                size = fInfo.st_size
                sha1 = hashlib.sha1(open(rawPath).read()).hexdigest()
                details = FileInfoDetail.objects(info=file, sha1=sha1, size=size, filePath=filePath)
                detail = None
                if len(details) > 0:
                    detail = details[0]
                    if len(detail.svnVersion) == 0:
                        detail.svnVersion = getSvnInfo(rawPath)
                else:
                    detail = FileInfoDetail()
                    detail.filePath = filePath
                    detail.info = file
                    detail.createTime = datetime.datetime.fromtimestamp(fInfo.st_ctime)
                    detail.updateTime = datetime.datetime.fromtimestamp(fInfo.st_mtime)
                    detail.size = fInfo.st_size
                    detail.sha1 = hashlib.sha1(open(rawPath).read()).hexdigest()
                    detail.svnVersion = getSvnInfo(rawPath)
                    f = open(rawPath, "r")
                    detail.file.put(f)
                    f.close()
                fileDetails.append(detail)
    # 写入客户配置
    logger.info("add customer config")
    path = pathHelper.getLocalDir(machine.os) + "customer.lua"
    fileDetails.append(tryAddString(path, customer.settings))

    # 写入机器配置
    logger.info("add machine config")
    path = pathHelper.getLocalDir(machine.os) + "machine.lua"
    fileDetails.append(tryAddString(path, machine.settings))

    # 写入license.data
    logger.info("add license info")
    permissionMap = {}
    for k, v in customer.permissions.iteritems():
        permission = CustomerPermissionSettings.objects.get(pk=k)
        permissionMap[permission.name.strip()] = v
    licenseGenerator = LicenseDataGenerator(permissionMap, machine.code)
    str = licenseGenerator.gen()
    if not isWindows(machine.os) and not isThisWindows():
        # 写入授权文件
        f = open("/home/rzrk/server/license/license.data", "w")
        f.write(str)
        f.close()

        fileDetails.append(tryAddString(pathHelper.getLicensePath(machine.os, machine.xtDir), str))
        # 拷贝公钥，
        fileDetails.append(tryAddFile("server/bin/pubkey.pem", "/home/rzrk/server/license/pubkey.pem"))
        Popen(["/usr/bin/python", "/home/rzrk/server/license/gen.py"]).communicate()
        fileDetails.append(tryAddFile("server/bin/license.sign", "/home/rzrk/server/license/license.sign"))
    print isWindows(machine.os)
    if not isWindows(machine.os):
        # 写入运行信息
        logger.info("add run info")
        runInfos = []
        for module in machine.modules:
            runInfos.extend(module.runInfos)

        for info in runInfos:
            path, script = info.getRunScript(machine.os, machine.xtDir)
            if path is not None:
                fileDetails.append(tryAddString(path, script, 755))


        # 写入dailyRestart

        logger.info("add dailyRestart.sh")
        logger.info("add win_dailyRestart.bat")
        path = "server/monitor/dailyRestart.sh"
        fileDetails.append(tryAddString(path, genDailyRestart(runInfos), 755))

        # 增加checkAll
        logger.info("add check all")
        strCheckAll = genCheckAll(runInfos, machine.xtDir)
        strCheckAll = strCheckAll + "\n" + "/home/rzrk/server/monitor/checkBroker.sh"
        fileDetails.append(tryAddString("server/monitor/checkAll.sh", strCheckAll, 755))

        # 写入crontab信息
        logger.info("add crontable ")
        strCronTable = getCrontable(runInfos, machine.xtDir)
        fileDetails.append(tryAddString("crontab", strCronTable))
      

        # 写入平台信息
        logger.info("add platform ")
        strPlatform = genPlatform(machine.modules)
        fileDetails.append(tryAddString("server/config/platform.lua", strPlatform))

        # 写入keepalived配置
        for module in machine.modules:
            if module.name == "KeepAlived_master":
                str = replaceStr(KEEPALIVED_MASTER_CONFIG, {"virtualIp": customer.virtual_ip})
                fileDetails.append(tryAddString("keepalived/conf/keepalived.conf", str))
            elif module.name == "KeepAlived_slave":
                str = replaceStr(KEEPALIVED_SLAVE_CONFIG, {"virtualIp": customer.virtual_ip})
                fileDetails.append(tryAddString("keepalived/conf/keepalived.conf", str))

        if len(customer.machines) == 2:
            # 写入notify.sh
            localDir = os.path.dirname(os.path.abspath(__file__))
            path = localDir + "/../deploy/notify.sh"
            str = open(path, "r").read()
            data = {"isMasterBackup": "1", "checkRedis": "{{xtDir}}/server/monitor/checkRedis.sh", "xtDir": machine.xtDir}
            str = replaceStr(str, data)
            fileDetails.append(tryAddString("server/monitor/notify.sh", str, 755))

            # 写入checkRedis.sh
            localDir = os.path.dirname(os.path.abspath(__file__))
            path = localDir + "/../deploy/checkRedis.sh"
            str = open(path, "r").read()
            otherHost = ""
            for m in customer.machines:
                if m != machine:
                    otherHost = m.name
                    break
            data = {"otherHost": otherHost}
            str = replaceStr(str, data)
            fileDetails.append(tryAddString("server/monitor/checkRedis.sh", str, 755))
        else:
            # 写入notify.sh
            data = {"isMasterBackup": "0", "checkRedis": ""}
            localDir = os.path.dirname(os.path.abspath(__file__))
            path = localDir + "/../deploy/notify.sh"
            str = open(path, "r").read()
            str = replaceStr(str, data)
            fileDetails.append(tryAddString("server/monitor/notify.sh", str))

    else:
        logger.info("add run info")
        runInfos = []
        for module in machine.modules:
            runInfos.extend(module.runInfos)
        print "runInfos: %s"%runInfos
        for info in runInfos:
            win_path,win_script = info.getRunScript(machine.os, machine.xtDir)
            if win_path is not None:
                fileDetails.append(tryAddString(win_path, win_script, 755))

        # 写入dailyRestart

        logger.info("add win_dailyRestart.bat")
        win_path = "server/monitor/win_dailyRestart.bat"
        fileDetails.append(tryAddString(win_path, replaceStr(win_genDailyRestart(runInfos),{"xtDir": machine.xtDir}), 755))

        # 写入crontab信息
        logger.info("add crontable ")
        win_strCronTable = win_getCrontable(runInfos,machine.xtDir)
        print 'runInfos:%s' % runInfos
        print type(runInfos)
        print 'runInfos:%s' % runInfos[0].timerParam
        print 'machine.xtDir :%s '% machine.xtDir
        fileDetails.append(tryAddString("win_crontab.bat", win_strCronTable))

    for file in fileDetails:
        logger.info("save file [%s]" % file.filePath)
        file.save()

    # 产生的文件
    logger.info("gen package")
    installPackage = InstallPackage()
    installPackage.version = "%s_%s_%s" % (customer.name, machine.name, datetime.datetime.now().strftime("%Y%m%d"))
    installPackage.customer = customer
    installPackage.machine = machine
    installPackage.files = fileDetails
    installPackage.create_user = user
    installPackage.branches = ",".join(["%s/%s" % (k, v) for k, v in branchMap.iteritems()])
    installPackage.svn_info = generator_svn_info(branchMap)
    installPackage.remark = remark
    logger.info("package saved")

    return True, '(%s[id=%s]-%s[id=%s]) 生成成功!' % (customer.name, customer.id, machine.name, machine.id), installPackage


def generator_svn_info(branchMap):
    """
    生成安装包的SVN信息
    """
    svn_info = {}
    try:
        client = pysvn.Client()

        for key in branchMap:
            value = branchMap[key]
            entry = client.info(value)
            svn_branch = value

            svn_url = entry.url
            svn_commit_revision = entry.commit_revision.number
            svn_commit_time = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(entry.commit_time))
            svn_author = entry.commit_author

            # 获取日志
            revision_start = pysvn.Revision(pysvn.opt_revision_kind.number, svn_commit_revision)
            revision_end = pysvn.Revision( pysvn.opt_revision_kind.number, 175324)
            data = client.log(svn_url, revision_start=revision_start, revision_end=revision_end, limit=1)[0].data
            svn_message = data.get('message', '')
           
            svn_info[svn_url] = [svn_author, svn_commit_revision, svn_commit_time, svn_message]
        logger.info('打包时获取SVN信息成功!参数信息:[%s] ; 结果信息:[%s]' % (json.dumps(branchMap, ensure_ascii=False), json.dumps(svn_info, ensure_ascii=False)))
        return json.dumps(svn_info, ensure_ascii=False)
    except Exception as e:
        logger.error('打包时获取SVN信息失败!错误信息:[%s-%s]参数信息:[%s]' % (e.message, getTraceBack(), json.dumps(branchMap, ensure_ascii=False)))
        return '{}'

def getSvnLog(request):
    """  
    获取特定分支的SVN日志
    """
    if request.method == 'GET':
        branch = request.GET.get('branch', None)
        try: 
            client = pysvn.Client()
            entry = client.info(branch)

            svn_url = entry.url
            svn_commit_revision = entry.commit_revision.number
            svn_commit_time = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(entry.commit_time))
            svn_author = entry.commit_author
            # 获取日志
            revision_start = pysvn.Revision(pysvn.opt_revision_kind.number, 180503)
            revision_end = pysvn.Revision(pysvn.opt_revision_kind.number, 175324)

            results = []
            for log in client.log(svn_url,
                revision_start=revision_start,
                revision_end=revision_end,
                discover_changed_paths=True,
                strict_node_history=True,
                limit=0):

                revision = log.revision.number
                author = log["author"]
                message = log["message"]               
                results.append([revision, author, message])
           
            return render_to_response('customer/include/customer_svn_log_read.html', locals(), context_instance=RequestContext(request))

        except Exception as e:
            svn_log = "加载日志异常![%s]" % str(e)
            return render_to_response('customer/include/customer_svn_log_read.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def remark_list(request):
    """
    客户备注列表
    :param request:
    :return:
    """
    if request.method == 'GET':
        try:
            remarks = CustomerTip.objects().order_by('-update_time', '-create_time')
            return render_to_response("customer/customer_remark_list.html", locals(), context_instance=RequestContext(request))
        except Exception as e:
            error = '程序异常![%s][%s]' % (e.message, getTraceBack())
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    else:
        response = {'success': False, 'error': '请使用http-get方式请求!'}
        return HttpResponse(json.dumps(response), mimetype="application/json")


@csrf_exempt
@login_required
def deploy_status(request):
    """
    检查客户部署程序更新状态
    :param request:
    :return:
    """
    response = {'success': False, 'error': ''}
    if request.method == 'GET':
        try:
            # 获取参数
            json_str = request.GET.get('json', None)

            if json_str is None:
                response['error'] = '必要参数为空!'
                return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

            cus_id_arr = json.loads(json_str)

            result = []

            svn_util = SvnUtils()

            for cus_id in cus_id_arr:
                customer = Customer.objects.get(pk=cus_id)
                cus_json = {'cus_id': cus_id, 'cus_name': customer.name, 'machines': []}

                machines = customer.machines
                for machine in machines:
                    machine_json = {
                        'machine_id': str(machine.id),
                        'machine_name': machine.name,
                        'server': {
                            'usable': False,
                            'is_old': False,
                            'svn_info': []
                        },
                        'portal': {
                            'usable': False,
                            'is_old': False,
                            'svn_url': '',
                            'previous_revision': '',
                            'current_revision': '',
                            'key_submits': []
                        }
                    }

                    # 最后一条更新记录
                    records = DeployRecord.objects(customer=customer, machine=machine).order_by("-start_time")

                    if len(records) == 0:
                        cus_json['machines'].append(machine_json)
                        continue

                    record = records[0]

                    # 编辑是否为最新版本
                    server_is_old = False
                    server_package = record.new_version
                    if server_package is not None and type(server_package) != DBRef:
                        svn_info = server_package.svn_info
                        if svn_info:
                            svn_info = json.loads(svn_info)
                            for svn_url in svn_info:
                                value = svn_info[svn_url]
                                previous_revision = value[1]

                                # TODO 待删除,无权限
                                # if svn_url.find('broker') != -1:
                                # continue

                                # 根据版本号获取submit情况
                                current_revision = svn_util.get_current_svn_revision(svn_url)
                                branch_is_old = False
                                if current_revision != previous_revision:
                                    server_is_old = True
                                    branch_is_old = True

                                server_json = {
                                    'svn_url': svn_url,
                                    'previous_revision': previous_revision,
                                    'current_revision': current_revision,
                                    'is_old': branch_is_old,
                                    'key_submits': []
                                }

                                server_key_submits = svn_util.get_key_submit_by_revision(svn_url, previous_revision, revision_start=current_revision)
                                # 记录关键更新
                                for key_submit in server_key_submits:
                                    server_json['key_submits'].append({
                                        'start': key_submit.revision_start,
                                        'end': key_submit.revision_end,
                                        'remark': key_submit.remark
                                    })

                                machine_json['server']['svn_info'].append(server_json)
                                machine_json['server']['is_old'] = server_is_old

                    machine_json['server']['usable'] = True

                    portal_package = record.portal_package
                    if portal_package is not None:
                        svn_url = portal_package.svn_url
                        previous_revision = int(portal_package.svn_version)
                        print previous_revision
                        current_revision = svn_util.get_current_svn_revision(svn_url)
                        portal_is_old = False
                        if current_revision != previous_revision:
                            portal_is_old = True

                        machine_json['portal']['is_old'] = portal_is_old
                        machine_json['portal']['svn_url'] = svn_url
                        machine_json['portal']['previous_revision'] = previous_revision
                        machine_json['portal']['current_revision'] = current_revision

                        key_submits = svn_util.get_key_submit_by_revision(svn_url, previous_revision, revision_start=current_revision)
                        # 记录关键更新
                        for key_submit in key_submits:
                            machine_json['portal']['key_submits'].append({
                                'start': key_submit.revision_start,
                                'end': key_submit.revision_end,
                                'remark': key_submit.remark
                            })

                    machine_json['portal']['usable'] = True
                    cus_json['machines'].append(machine_json)

                result.append(cus_json)

            response['data'] = result
            response['success'] = True
            return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
        except Exception as e:
            error = '程序异常![%s][%s]' % (e.message, getTraceBack())
            logger.error(error)
            response['error'] = error
            return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
    else:
        response['error'] = '请使用http-get方式请求!'
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")






def check_one_machine_status(customerdeploystatus):

    if customerdeploystatus.portal_svn_url == '' and (len(customerdeploystatus.server_svn_info) == 0):

        return 'unknow'

    if customerdeploystatus.portal_is_old and len(customerdeploystatus.portal_key_submits) == 0 or (customerdeploystatus.server_is_old and  not check_server_has_key_submit(customerdeploystatus.server_svn_info)):
        return 'old'


    if customerdeploystatus.portal_is_old and len(customerdeploystatus.portal_key_submits) != 0 or (customerdeploystatus.server_is_old and check_server_has_key_submit(customerdeploystatus.server_svn_info)):
        return 'old_key'

def check_server_has_key_submit(server_svn_infos):
    for index in server_svn_infos:
        svn_info = server_svn_infos[index]
        if svn_info.key_submits.length > 0:
            return True
    return False

def get_cus_flag_name(customerdeploystatus):

        if len(customerdeploystatus) == 0:
            return 'unknown'

        machines = customerdeploystatus.machines
        results = []

        for machine in machines:
            results.append(check_one_machine_status(customerdeploystatus))

        unknown_time = 0
        old_time = 0

        for result in results:
            if result == 'old_key':
                return 'old_key'

            if result == 'unknown':
                unknown_time += 1

            if result == 'old':
                old_time += 1

        if old_time > 0:
            return 'old'

        if unknown_time == len(results):
            return 'unknown'

        return 'newest'


def download_base_soft(request):
    try:
        customerId = request.GET.get("cus_id", None)
        customer = Customer.objects.get(pk=customerId)

        if not customerId:
            error = "必要参数为空!"
            logger.error(error)

        ip_addr = [machine.name for machine in customer.machines]

        file0 = "/home/rzrk/ServerInitScript/ServerInitSingle.sh"
        file1 = "/home/rzrk/ServerInitScript/ServerInitDouble/ServerInitDouble.sh"
        file2 = "/home/rzrk/ServerInitScript/ServerInitDouble/ServerInitMaster.sql"
        file3 = "/home/rzrk/ServerInitScript/ServerInitDouble/ServerInitBackup.sql"

        for file in [file0, file1, file2, file3]:
            if not os.path.exists(file):
                error = "未找到对应文件!"
                logger.error(error)
                return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

        if len(customer.machines) == 1:
            fp0 = open(file0, "r")
            size = file.size
            response = HttpResponse(file1.read())
            response['Content-Length'] = size
            response['Content-Disposition'] = 'attachment; filename=%s' % fp0
            return response

        fileDetails = []
        if len(customer.machines) == 2:
            str = replaceStr(MYSQL_MASTER_CONFIG, {"IpAddr": ip_addr[1]})
            fileDetails.append(tryAddString("/home/rzrk/ServerInitScript/ServerInitDouble/ServerInitMaster.sql", str))
            str = replaceStr(MYSQL_SLAVE_CONFIG, {"IpAddr": ip_addr[0]})
            fileDetails.append(tryAddString("/home/rzrk/ServerInitScript/ServerInitDouble/ServerInitBackup.sql", str))

            if os.path.exists('/home/soft/RzrkServerDouble.zip'):
                os.remove("RzrkServerDouble.zip")
            #with zipfileG.ZipFile('RzrkServerDouble.zip', 'w') as myzip:
            #    myzip.write('RzrkServerDouble')

            fp4 = open("/home/soft/RzrkServerDouble.zip", "r")
            size = fp4.size
            response = HttpResponse(fp4.read())
            response['Content-Length'] = size
            response['Content-Disposition'] = 'attachment; filename=%s' % fp4
            return response

    except Exception as e:
        error = "下载文件异常![%s]" % str(e)
        logger.error(error + getTraceBack())
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


def sftp_makedirs(sftp, dir):
    dir = dir.replace("\\", "/")
    items = dir.split("/")
    items = [item for item in items if len(item) > 0]

    ownedIndex = 0
    for index in xrange(1, len(items) + 1):
        nowDir = "/" + "/".join(items[0:index])
        try:
            d = sftp.stat(nowDir)
            if not stat.S_ISDIR(d.st_mode):
                ownedIndex = index
                break
        except:
            ownedIndex = index
            break

    for index in xrange(ownedIndex, len(items) + 1):
        nowDir = "/" + "/".join(items[0:index])
        logger.info("make dir %s" % nowDir)
        try:
            sftp.mkdir(nowDir)
        except IOError:
            logger.info('%s already exists' % nowDir)


def server_update(client, sftp, customer, machine, finfo, update_root_path='/home/rzrk/update/', package_name=""):
    global deployINFO
    server_package_path = update_root_path + package_name
    sftp_makedirs(sftp, update_root_path)
    try:
        deployINFO = "正在升级server包"
        sftp.put('%s/../deploy/update.sh' % settings.MEDIA_ROOT, update_root_path + 'update.sh')
    except:
        return {'success': False, 'msg': '[%s_%s] fail to copy \"update.sh\" from local to server dir: %s' % (customer.name, machine.host, update_root_path)}
    try:
        logger.info('begin to send data: %s begin' % server_package_path)
        sftp.putfo(finfo, server_package_path)
        logger.info('begin to send data: %s end' % server_package_path)
    except:
        return {'success': False, 'msg': '[%s_%s] fail to copy install package to remote server dir: \"%s\"' % (customer.name, machine.host, server_package_path)}

    client.exec_command('chmod +x ' + update_root_path + 'update.sh')

    cmd = 'cd %s; /bin/sh update.sh %s' % (update_root_path, package_name)
    logger.info('executing: %s begin' % cmd)
    stdin, stdout, stderr = client.exec_command(cmd)
    logger.info('executing: %s end' % cmd)
    error = stderr.read()
    if len(error) > 0:
        msg = '[%s_%s]executing cmd %s failed, %s' % (customer.name, machine.host, cmd, error)
        logger.info(msg)
        return {'success': True, 'msg': "excueted success"}
    else:
        logger.info('successfully execute cmd: %s' % cmd)
    return {'success': True, 'msg': '[%s_%s] update server successfully' % (customer.name, machine.host)}


def portal_update(client, sftp, customer, machine, finfo, root_path='/home/rzrk/webserver/', package_name=''):
    global deployINFO
    deployINFO = "正在升级portal"
    # 远程传输 portal 安装包
    portal_package_path = root_path + package_name
    try:
        sftp.putfo(finfo, portal_package_path)
    except:
        msg = '[%s_%s_update_portal] 拷贝portal安装包到服务器 失败: %s' % (customer.name, machine.host, portal_package_path)
        return {'success': False, 'msg': msg}
    cmd = 'cd %s; /bin/tar -zxvf %s -C /home/rzrk/webserver/webserver' % (root_path, package_name)
    logger.info('excute command: %s begin' % cmd)
    stdin, stdout, stderr = client.exec_command(cmd)
    logger.info('excute command: %s end' % cmd)
    logger.info('excute command: killall python')
    client.exec_command('killall python')
    out = stdout.readlines()
    err_list = stderr.readlines()
    if len(err_list) > 0:
        msg = '[%s_%s__portal] 解压 %s 失败 error message: %s' % (customer.name, machine.host, package_name, str(err_list))
        logger.info(msg)
        return {'success': False, 'msg': msg}
    else:
        msg = '[%s_%s__portal] 解压 %s 成功' % (customer.name, machine.host, package_name)
        logger.info(msg)
        return {'success': True, 'msg': msg}

@csrf_exempt
@login_required
def update_customer_package(request):
    response = {'success': False, 'error': ''}
    try:
        cus_package_id = request.POST.get("id", None)
        customerPack = CustomerPackage.objects.get(pk=cus_package_id)
        logger.info('[%s] begin to auto deploy by user %s' % (customerPack.customer.name, request.user.username))

        res_list = list()
        customerStartTime = datetime.datetime.now()

        # 更新portal
        portalPack = customerPack.portal_package
        content = portalPack.package.read()
        portalIO = StringIO(content)

        for machinePack in customerPack.machine_packages:
            logger.info('[%s] begin to auto deploy machine %s by user %s' % (customerPack.customer.name, machinePack.machine.name, request.user.username))
            startTime = datetime.datetime.now()
            machine = machinePack.machine
            stringIO = StringIO(gen_update_package(machinePack))

            # 建立连接
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(machine.host, machine.port, username=machine.username, password=machine.password)
            sftp = paramiko.SFTPClient.from_transport(client.get_transport())

            # 更新主程序
            res = server_update(client, sftp, customerPack, machinePack.machine, stringIO, "/home/rzrk/update/", "auto_deploy_server_%s_install.tar.gz" % datetime.datetime.now().strftime("%Y%m%d"))
            if not res['success']:
                client.close()
                return HttpResponse(json.dumps(str(res)), mimetype="application/json")
            else:
                res_list.append(res)

            # 更新portal
            res = portal_update(client, sftp, customerPack.customer, machine, portalIO, "/home/rzrk/update/", "auto_deploy_portal_%s_%s.tar.gz" % (datetime.datetime.now().strftime("%Y%m%d"), portalPack.svn_version))
            if not res['success']:
                client.close()
                return HttpResponse(json.dumps(str(res)), mimetype="application/json")
            else:
                res_list.append(res)

            # 更新mysql
            if machinePack == customerPack.machine_packages[0]:
                if len(customerPack.portal_upgrade_sql) > 0:
                    sqlIO = StringIO(customerPack.portal_upgrade_sql)
                    sqlPath = "/home/rzrk/update/%s.sql" % datetime.datetime.now().strftime("%Y%m%d")
                    sftp.putfo(sqlIO, sqlPath)
                    cmd = '/usr/bin/python /home/rzrk/update/_update/Deploy.py %s' % sqlPath
                    logger.info("excute %s" % cmd)
                    stdin, stdout, stderr = client.exec_command(cmd)
                    out = stdout.readlines()
                    err_list = stderr.readlines()
                    if len(err_list) > 0:
                        logger.info('[%s excuete sql error %s] ' % (customerPack.customer.name, "\n".join(err_list)))
                    else:
                        logger.info('[%s excuete sql %s] ' % (customerPack.customer.name, "\n".join(out)))
            client.close()

            logger.info('[%s] end of auto deploy machine %s by user %s' % (customerPack.customer.name, machinePack.machine.name, request.user.username))

            # 增加升级记录
            deployRecord = DeployRecord()
            deployRecord.customer = machinePack.customer
            deployRecord.machine = machinePack.machine
            deployRecord.new_version = machinePack
            deployRecord.portal_package = portalPack
            deployRecord.portal_upgrade_sql = customerPack.portal_upgrade_sql
            deployRecord.start_time = startTime
            deployRecord.end_time = datetime.datetime.now()
            deployRecord.deploy_user = request.user.username
            deployRecord.remark = "auto deploy"
            deployRecord.create_time = datetime.datetime.now()
            deployRecord.create_user = request.user
            deployRecord.generatorJson = ""
            deployRecord.save()

            logger.info('[%s] added machine %s deploy record by user %s' % (customerPack.customer.name, machinePack.machine.name, request.user.username))

        customerDeployRecord = CustomerDeployRecord()
        customerDeployRecord.customer = customerPack.customer
        customerDeployRecord.cus_package = customerPack
        customerDeployRecord.portal_upgrade_sql = customerPack.portal_upgrade_sql
        customerDeployRecord.start_time = customerStartTime
        customerDeployRecord.end_time = datetime.datetime.now()
        customerDeployRecord.deploy_user = request.user.username
        customerDeployRecord.remark = "auto deploy"
        customerDeployRecord.create_time = datetime.datetime.now()
        customerDeployRecord.create_user = request.user
        customerDeployRecord.save()
        logger.info('[%s] added customer deploy record by user %s' % (customerPack.customer.name, request.user.username))

        response['success'] = True
        response['error'] = res_list
    except Exception as e:
        error = "远程部署异常![%s][%s]" % (str(e), getTraceBack())
        logger.error(error)
        response['error'] = error

    return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")




@csrf_exempt
@login_required
def permission_setting(request):
    """
    客户权限表
    :param request:
    :return:
    """
    if request.method == 'GET':
        settings = CustomerPermissionSettings.objects()
        value_type_list = CustomerPermissionSettings.get_value_type()
        customers = Customer.objects()
        settings2 = list()
        for setting in settings:
            settings2.append(str(setting.id))
        return render_to_response("customer/customer_permission_setting.html", locals(), context_instance=RequestContext(request))
    elif request.method == 'POST':
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


@csrf_exempt
@login_required
def permission_setting_update(request):
    """
    客户权限表
    :param request:
    :return:
    """
    if request.method == 'GET':
        response = {'success': False, 'error': u'非法请求方式'}
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
    elif request.method == 'POST':
        response = {'success': True, 'error': 'You did it!!!'}
        values = request.POST.get('values')
        cust_id = request.POST.get('id')

        values = values.strip(',')
        value_list = values.split(',')
        perm_settings = CustomerPermissionSettings.objects()
        customer = Customer.objects().get(pk=cust_id)
        cust_permissions = customer.permissions
        index = 0
        for perm_setting in perm_settings:
            perm_id = str(perm_setting.id)
            try:
                if cust_permissions[perm_id] != value_list[index]:
                    cust_permissions[perm_id] = value_list[index]
                index += 1
            except Exception as e:
                print str(e)
        customer.permissions = cust_permissions

        customer.save()

        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

@csrf_exempt
@login_required
def create_tag(request):
    # 根据客户包 id 创建 tag
    if request.method == 'POST':
        error =  u'非法请求方式，请使用 http-get方式请求'
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
    else:
        package_id = request.GET.get('package_id', None)
        customer_tag = request.GET.get("customer_tag", None)

        src_version = -1
        src_branch = "trunk"
        dst_branch = "tags/"

        package = InstallPackage.objects.get(pk=package_id)
        if package is None:
            error = '未找到安装包'
            return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))
        if customer_tag is not None:
            dst_branch = "tags/" + customer_tag + "_" + datetime.datetime.now().strftime("%Y%m%d")
        branches = PROGRAM_LIST4SVN

        return render_to_response('programBranch/programTag_create.html', locals(), context_instance=RequestContext(request))

@csrf_exempt
@login_required
def portalDefaultBranch(request):
    response = {'success': False, 'error': ''}
    if request.method == 'GET':
        # get value
        customerID = request.GET.get("customerID", None)
        portal_package_id = request.GET.get("portal_package_id", None)
        customer = Customer.objects.get(pk=customerID)
        portal_package = PortalPackage.objects.get(pk=portal_package_id)

        # find info and save
        defaultInfo = PortalDefaultBranch.objects(customer=customer)
        if not defaultInfo:
            defaultInfo = PortalDefaultBranch()
        else:
            defaultInfo = defaultInfo[0]
        defaultInfo.customer = customer
        defaultInfo.svn_version = portal_package.svn_version
        if portal_package.svn_url.find('/server5/')>0:
            arr=portal_package.svn_url.split(SVN_ROOT + 'server5/')[1].split('/',1)
        else:
            arr=portal_package.svn_url.split(SVN_ROOT)[1].split('/',1)

        defaultInfo.branch_tag=arr[1]

        defaultInfo.save()

        response['success'] = True
        response['error'] = '执行成功!'
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")



@csrf_exempt
@login_required
def portalDefaultBranch(request):
    response = {'success': False, 'error': ''}
    if request.method == 'GET':
        # get value
        customerID = request.GET.get("customerID", None)
        portal_package_id = request.GET.get("portal_package_id", None)
        customer = Customer.objects.get(pk=customerID)
        portal_package = PortalPackage.objects.get(pk=portal_package_id)

        # find info and save
        defaultInfo = PortalDefaultBranch.objects(customer=customer)
        if not defaultInfo:
            defaultInfo = PortalDefaultBranch()
        else:
            defaultInfo = defaultInfo[0]
        defaultInfo.customer = customer
        defaultInfo.svn_version = portal_package.svn_version
        if portal_package.svn_url.find('/server5/')>0:
            arr=portal_package.svn_url.split(SVN_ROOT + 'server5/')[1].split('/',1)
        else:
            arr=portal_package.svn_url.split(SVN_ROOT)[1].split('/',1)

        defaultInfo.branchtag=arr[1]

        defaultInfo.save()

        response['success'] = True
        response['error'] = '执行成功!'
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")	


@csrf_exempt
@login_required
def saveDefaultBranch(request):
    response = {'success': False, 'error': ''}
    if request.method == 'GET':
        # get value
        customerID = request.GET.get("customerID", None)
        programName = request.GET.get("programName", None)
        branchTag = request.GET.get("branchTag", None)
        customer = Customer.objects.get(pk=customerID)

        # find info and save
        defaultInfo = CustomerDefaultBranch.objects(customer=customer, programName=programName)
        if not defaultInfo:
            defaultInfo = CustomerDefaultBranch()
        else:
            defaultInfo = defaultInfo[0]
        defaultInfo.customer = customer
        defaultInfo.programName = programName
        defaultInfo.branchTag = branchTag
        defaultInfo.save()

        response['success'] = True
        response['error'] = '执行成功!'
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

def clientDefaultBranch(request):
    response = {'success': False, 'error': ''}
    # get value
    customerID = request.GET.get("customerID", None)
    programName = request.GET.get("programName", None)
    branchTag = request.GET.get("branchTag", None)
    customer = Customer.objects.get(pk=customerID)

    # find info and save
    clientInfo = ClientDefaultBranch.objects(customer=customer, programName=programName)
    if not clientInfo:
        clientInfo = ClientDefaultBranch()
    else:
        clientInfo = clientInfo[0]
    clientInfo.customer = customer
    clientInfo.programName = programName
    clientInfo.branchTag = branchTag
    clientInfo.save()

    response['success'] = True
    response['error'] = '执行成功!'
    return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

@csrf_exempt
@login_required
def state_list(request):
    response = {"success": False, "error": ""}
    if request.method == 'GET':
        try:
            # 参数
            id = request.GET.get('id', None)
            customerdeploystatus = CustomerDeployStatus.objects.get(pk = id)
            response["success"] = True
            response["data"] = customerdeploystatus
            response["error"] = "执行成功!"
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")




@csrf_exempt
@login_required
def compare(request):
    response = {"success": False, "error": ""}
    if request.method == 'GET':
        try:
            # 获取参数
            json_str = request.GET.get('json', None)
            if json_str is None:
                response['error'] = '必要参数为空!'
                return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

            cus_id_arr = json.loads(json_str)
            for key in cus_id_arr:
                cus_id = cus_id_arr[key]
                customer = Customer.objects.get(pk=cus_id)
                machine_json = {'portal_svn_info': [], 'server_svn_info': []}
                portal_is_old = False
                server_is_old = False
                if not customer.machines:
                    continue
                machines = customer.machines

                records = CustomerDeployRecord.objects(customer=customer).order_by("-start_time")

                server_key_submits = []
                portal_key_submits = []

                if len(records) == 0:
                    continue
                record = records[0]
                cus_pack = record.cus_package
                portal_package = cus_pack.portal_package
                server_pack = cus_pack.machine_packages[0]
                if not server_pack:
                    response['error'] = '查找server包失败!'
                    return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
                if not portal_package:
                    response['error'] = '查找portal包失败!'
                    return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")

                #判断portal的svn_url和server的svn_url是否存在
                if not portal_package.svn_url and not server_pack.svn_info:
                    continue
                if portal_package.svn_url:
                    machine_json['portal_svn_info'], portal_is_old, portal_key_submits = get_portal_status(portal_package)

                if server_pack.svn_info:
                    machine_json['server_svn_info'], server_is_old, server_key_submits = get_serve_status(server_pack.svn_info)

                customerdeploystatus  = CustomerDeployStatus(customer = customer)
                if not customerdeploystatus:
                    customerdeploystatus = CustomerDeployStatus()

                if (portal_is_old and portal_key_submits) or (server_key_submits and server_is_old):
                    customerdeploystatus.portal_svn_info = machine_json['portal_svn_info']
                    customerdeploystatus.server_svn_info = machine_json['server_svn_info']
                    customerdeploystatus.state = '关键更新'
                elif (portal_is_old) or (server_is_old):
                    customerdeploystatus.portal_svn_info = machine_json['portal_svn_info']
                    customerdeploystatus.server_svn_info = machine_json['server_svn_info']
                    customerdeploystatus.state = '有更新'
                else :
                    customerdeploystatus.state = '未知'
                customerdeploystatus.portal_is_old = portal_is_old
                customerdeploystatus.server_is_old = server_is_old
                customerdeploystatus.machines = machines
                customerdeploystatus.create_time = datetime.datetime.now()
                customerdeploystatus.save()
            response['success'] = True
            response['error'] = "更新数据库成功！"
            return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
        except Exception as e:
            error = '程序异常![%s][%s]' % (e.message, getTraceBack())
            logger.error(error)
            response['error'] = error
            return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")
    else:
        response['error'] = '请使用http-get方式请求!'
        return HttpResponse(json.dumps(response, ensure_ascii=False), mimetype="application/json")


@csrf_exempt
@login_required
def status(request):
    response = {"success": False, "error": ""}
    if request.method == 'GET':
        try:
            cus_id = request.GET.get('cus_id')
            print 'cus_id :%s' % cus_id
            if not cus_id:
                response['error'] = '客户ID为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects(pk=cus_id)
            customer = customer[0]
            if len(customer) == 0:
                response['error'] = '未能获取客户对象!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            cus_status = CustomerDeployStatus.objects(customer=customer).order_by('-create_time')
            cus_status = cus_status[0]
            machines = cus_status.machines
            portal_svn_info = cus_status.portal_svn_info
            server_is_old = cus_status.server_is_old
            portal_is_old = cus_status.portal_is_old
            if len(cus_status.server_svn_info) > 0:
                LEN = 1+len(cus_status.server_svn_info)
            else :
                LEN = 2
            t = get_template('customer/include/customer_state_list.html')
            html = t.render(Context({'cus_status': cus_status, 'machines': machines,'portal_svn_info':portal_svn_info,'LEN':LEN,'portal_is_old':portal_is_old,'server_is_old':server_is_old}))

            response['success'] = True
            response['data'] = str(html)
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))

#跳转到portal页面
@csrf_exempt
@login_required
def switch_portal(request):
    response = {"success": False, "error": ""}
    if request.method == 'GET':
        try:
            cus_id = request.GET.get('cus_id')
            print 'cus_id :%s' % cus_id
            if not cus_id:
                response['error'] = '客户ID为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            customer = Customer.objects(pk=cus_id)
            customer = customer[0]
            if len(customer) == 0:
                response['error'] = '未能获取客户对象!'
                return HttpResponse(json.dump(response), mimetype="application/json")

            outer_portal_ip = customer.outer_portal_ip
            print 'outer_portal_ip :%s' % outer_portal_ip
            if not outer_portal_ip:
                response['error'] = 'portal端ID为空!'
                return HttpResponse(json.dumps(response), mimetype="application/json")

            response['success'] = True
            response['data'] = str(outer_portal_ip)
            return HttpResponse(json.dumps(response), mimetype="application/json")
        except Exception as e:
            response["error"] = "系统异常![%s]" % str(e)
            logger.error(response["error"] + getTraceBack())
            return HttpResponse(json.dumps(response), mimetype="application/json")
    else:
        error = "非法请求方式!"
        logger.error(error)
        return render_to_response('item/temp.html', locals(), context_instance=RequestContext(request))


