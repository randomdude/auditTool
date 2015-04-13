#!/usr/bin/python

import os
import sys
import subprocess
import os.path
import tempfile
import filecmp
import stat
import shutil
import urwid
import pysvn
import importlib
from threading import Thread

# todo: make these class members
globalRes = None
globalAuditProgress = 0
globalplsdie = False
globallastdeb = '...'
globalfinished = False

class package:
	name = None
	ver = None

	def __str__(self):
		return ('%s ver %s' % (self.name, self.ver,))

# a fake package we hang eny 'extra files to verify' from.
fakePkg = package()
fakePkg.name = '[none]'
fakePkg.ver = '1.0'

class singlefileresult:
	pkg = None
	filename = None

	expectedPerms = None
	actualPerms = None
	expectedgid = None
	actualgid = None
	expecteduid = None
	actualuid = None

	def __init__(self, parentPkg):
		self.pkg = parentPkg

	def __str__(self):
		return ('%s (%s)' % (self.filename, self.pkg,))

class uidandgid:
	uid = 0
	gid = 0

class auditresult:
	goodfiles = list()
	badfiles = list()
	missingfiles = list()
	changedpermissions = list()
	changedownership = list()
	badpackages = list()
	extrafiles = list()

	def printResults(res):
		print 'Good files:%d' % len(res.goodfiles)
		#	for goodfile in goodfiles:
		#		print '\t%s' % goodfile
		print 'Bad files:%d' % len(res.badfiles)
		for file in res.badfiles:
			print '\t%s' % file
		print 'Missing files:%d' % len(res.missingfiles)
		for file in res.missingfiles:
			print '\t%s' % file
		print 'Changed permissions :%d' % len(res.changedpermissions)
		for file in res.changedpermissions:
			print '\t%s' % file
		print 'Changed ownership :%d' % len(res.changedownership)
		for file in res.changedownership:
			print '\t%s' % file
		print 'Bad packages :%d' % len(res.badpackages)
		for file in res.badpackages:
			print '\t%s' % file

def getInstalledPackages():
	# Get a list of packages on the system.
	dpkglist = subprocess.Popen( ['dpkg', '--list', ('--root=%s'%targetroot)], stdout=subprocess.PIPE)
	stdout, stderr = dpkglist.communicate()

	if (dpkglist.returncode != 0):
		raise Exception ('dpkg returned non-zero status %d while --list\'ing packages' % dpkglist.returncode)

	toRet = list()
	for line in stdout.splitlines():
	#	print line
		tokens = line.split()
		state = tokens[0] 
		if (state == 'ii'):
			pkg = package()
			pkg.name = tokens[1].strip()
			if (':' in pkg.name):
				pkg.name = pkg.name.split(':')[0]
			pkg.ver = tokens[2]
			toRet.append(pkg)
	return toRet;

def getDeb(pkg):
	aptget = subprocess.Popen( ['apt-get', 'download', ('%s=%s'%(pkg.name, pkg.ver,) )], stdout=subprocess.PIPE)
	stdout, stderr = aptget.communicate()
	if (aptget.returncode != 0):
		return None
#		raise Exception ('apt-get returned non-zero status %d while attemting to download package %s version %s' % (aptget.returncode, pkg.name, pkg.ver, ) )
	verclean = pkg.ver
	if (':' in verclean):
		verclean = verclean.split(':')[1]
	# Look for a package specific to our arch
	debfilename = ('%s_%s_%s.deb' % (pkg.name, verclean, archstr,) )
	if not (os.path.isfile(debfilename)):
		# Maybe there's a generic package?
		debfilename = ('%s_%s_all.deb' % (pkg.name, verclean,) )
		if not (os.path.isfile(debfilename)):
			raise Exception ('apt-get download did not download file %s' % debfilename)

	return debfilename

def extractDeb(debname, outputdir):
	dpkglist = subprocess.Popen( ['dpkg', '--extract', debname, outputdir ], stdout=subprocess.PIPE)
	stdout, stderr = dpkglist.communicate()

	if (dpkglist.returncode != 0):
		raise Exception ('dpkg returned non-zero status %d while extracting package %s' % (dpkglist.returncode, debname, ))

def restoreToTarget(pkg):
	debname = getDeb(pkg.pkg)
	tempdir = tempfile.mkdtemp()
	extractDeb(debname, tempdir)

	src = os.path.join(tempdir, pkg.filename)
	dest = os.path.join(targetroot, pkg.filename)

	# Delete the destination, if it exists
	if os.path.islink(dest):
		os.unlink(dest)
	else:
		if os.path.isfile(dest):
			os.remove(dest)
		else:
			if os.path.isdir(dest):
				shutil.rmtree(dest)

	# Make the directory which stores the file.
	# FIXME: This doesn't set permissions
	dirname = os.path.dirname(dest)
	if not os.path.isdir(dirname):
		os.makedirs(dirname)

	# Copy the file
	if os.path.islink(src):
		# It's a symlink. Make a new one.
		linkto = os.readlink(src)
		os.symlink(linkto, dest)
	else:
		# Copy the file
		shutil.copyfile(src, dest)

	srcstats = os.lstat(src)
	
	# Also copy permissions
	# This won't work on debian based OS's. Apparently since POSIX doesn't mandate lchmod, Debian doesnt provide it, and
	# so python doesn't bother either. ick.
	#os.lchmod(dst, mode.st_mode)
	# and ownership
	os.lchown(dest, srcstats.st_uid, srcstats.st_gid)

	shutil.rmtree(tempdir)
	os.remove(debname)

def doDiff(pkg, isUnified):
	global ui

	tempDir = None
	badfile = os.path.join(targetroot, pkg.filename)

	# See if this file is in svn. If it is, diff against the svn version, and not a dpkg version.
	svnfile = os.path.join(ui.systemsvnpath, pkg.filename)
	if os.path.isfile(svnfile):
		# Yup, it's in SVN. Diff against that.
		goodfile = svnfile
	else:
		# Okay, go ahead and fetch a .deb to look at
		debname = getDeb(pkg.pkg)
		tempdir = tempfile.mkdtemp()
		extractDeb(debname, tempdir)
		goodfile = os.path.join(tempdir, pkg.filename)

	if isUnified:
		diff = subprocess.Popen( ['diff', '-u', goodfile, badfile  ], stdout=subprocess.PIPE)
	else:
		diff = subprocess.Popen( ['diff', goodfile, badfile  ], stdout=subprocess.PIPE)
	stdout, stderr = diff.communicate()

	if tempDir != None:
		shutil.rmtree(tempdir)
		os.remove(debname)
	return stdout

def verifyAllFiles(permittedChangesRoot):
	global globalAuditProgress
	res = auditresult()
	pkgList = getInstalledPackages()
	n = 0;
	totalPackages = len(pkgList)
	for pkg in pkgList:
		global globalplsdie
		if globalplsdie:
			return None
#		print 'Verifying pkg %s ver %s' % (pkg.name, pkg.ver,)
		global globallastdeb
		globallastdeb='(%d of %d): %s %s' % (n, totalPackages, pkg.name, pkg.ver, )

		debname = getDeb(pkg)
		if (debname == None):
			# We couldn't find this in the repo. :(
			res.badpackages.append(pkg)
			continue

		tempdir = tempfile.mkdtemp()
		extractDeb(debname, tempdir)
		verifyFiles(res, pkg, tempdir, permittedChangesRoot)

		shutil.rmtree(tempdir)
		os.remove(debname)

		if (n > 0):
			globalAuditProgress = (100/float(totalPackages)) * n
		n = n + 1
	
	# Verify any extra files we decided to check
	for extrafile in ui.extraFilesToCheck:
		fileres = singlefileresult(fakePkg)
		tgtpath = os.path.join(targetroot, extrafile)
		svnpath = os.path.join(permittedChangesRoot, extrafile)
		fileres.filename = extrafile
	#	fileres.expectedContentFilename = svnpath
		if not (os.path.isfile(svnpath) ):
			res.badfiles.append(fileres)
		else:
			if (filecmp.cmp(svnpath, tgtpath)):
				res.goodfiles.append(fileres)
			else:
				res.badfiles.append(fileres)
	return res;

	# Now add any 'extra' files we did not process.
	for root, dirs, files in os.walk(targetroot):
		for file in files:
			if (globalplsdie):
				return None
			fullpath = os.path.join(root, file)
			systemRelativePath = fullpath[len(targetroot)+1:]	# path relative to temp dir
			if systemRelativePath in res.goodfiles:
				continue
			if systemRelativePath in res.badfiles:
				continue
			if systemRelativePath in res.changedpermissions:
				continue
			if systemRelativePath in res.changedownership:
				continue

			permittedfile = os.path.join(permittedChangesRoot, systemRelativePath)
			if (os.path.isfile(permittedfile)):
				continue

			res.extrafiles.append(systemRelativePath)
	return res

def verifyFiles(res, pkg, tempdir, permittedChangesRoot):
	# Read permitted files/etc from SVN.
	allowedMissingFiles = list()
	with open (ui.missingfilessvnpath) as f:
		for line in f.readlines():
			allowedMissingFiles.append( line.strip() )
	with open (ui.modifiedpermssvnpath) as f:
		lines = f.readlines()
		permittedPermissions = dict()
		for line in lines:
			tok = line.split(',')
			permittedPermissions[tok[0]] = int(tok[1])
	with open (ui.modifiedownershipsvnpath) as f:
		lines = f.readlines()
		permittedOwnership = dict()
		for line in lines:
			tok = line.split(',')
			own = uidandgid()
			own.uid = int(tok[1])
			own.gid = int(tok[2])
			permittedOwnership[tok[0]] = own

	global globalplsdie
	for root, dirs, files in os.walk(tempdir):
		for file in files:
			if (globalplsdie):
				return None
			fullpath = os.path.join(root, file)		# path to file extracted from .deb 
			systemRelativePath = fullpath[len(tempdir)+1:]	# path relative to temp dir
			targetpath = os.path.join(targetroot, systemRelativePath)	# path to file on target FS

			fileres = singlefileresult(pkg)
			fileres.filename = systemRelativePath

			if not (os.path.exists(targetpath) or os.path.islink(targetpath) ):
				# The file is missing from the target system. Check if the list of permitted-missing files
				# mentions it.
				if not systemRelativePath.strip() in allowedMissingFiles:
					res.missingfiles.append(fileres)
			else:
				# If the _target_ file is a directory (the dpkg-extracted one won't be) then we should check
				# if we permit this. If we do, it'll be in SVN.
				if (not os.path.islink(targetpath) and os.path.isdir(targetpath)):
#					if not systemRelativePath in permittedFolderList:
					permittedfile = os.path.join(permittedChangesRoot, systemRelativePath)
					if (	os.path.isdir(permittedfile) ):
						res.goodfiles.append(fileres)
					else:
						res.badfiles.append(fileres)
					continue
				# If the target file is a symlink, handle that here
			 	tgtstat = os.lstat(targetpath)
				if stat.S_ISLNK(tgtstat.st_mode):
					# OK, the target filesystem has a symlink. Compare it to any symlink in svn
					tgt = os.readlink(targetpath)
					permittedfile = os.path.join(permittedChangesRoot, systemRelativePath)
					if (	os.path.isfile(permittedfile) or os.path.islink(permittedfile) ):
						# This file is in svn. If it isn't a symlink, then that's bad.
						statexp = os.lstat(permittedfile)
						if not stat.S_ISLNK(statexp.st_mode):
							res.badfiles.append(fileres)	# OK, svn file is present but not symlink
						else:
							# File is in svn and is a symlink. Verify it points to the right thing.
							tgtexp = os.readlink(permittedfile)
							if (tgt == tgtexp):
								res.goodfiles.append(fileres)
							else:
								res.badfiles.append(fileres)
					else:
						# This file is not in SVN. Compare it to the file in the deb.
						statexp = os.lstat(fullpath)
						if not stat.S_ISLNK(statexp.st_mode):
							res.badfiles.append(fileres)
						else:
							tgtexp = os.readlink(fullpath)
							if (tgt == tgtexp):
								res.goodfiles.append(fileres)
							else:
								res.badfiles.append(fileres)
				else:
					# Okay, compare file contents then. First see if this file is in svn
					permittedfile = os.path.join(permittedChangesRoot, systemRelativePath)
					if (	os.path.isfile(permittedfile) ):
						statexp = os.lstat(permittedfile)
						if (filecmp.cmp(permittedfile, targetpath)):
							res.goodfiles.append(fileres)
						else:
							res.badfiles.append(fileres)
					else:
						# Otherwise, just compare file contents.
						statexp = os.lstat(fullpath)
						if (filecmp.cmp(fullpath, targetpath)):
							res.goodfiles.append(fileres)
						else:
							res.badfiles.append(fileres)

				# Log any permission changes.
				if systemRelativePath in permittedPermissions:
					# There's a line in svn saying this file should have different permissions than the
					# default deb. Use those instead.
					fileres.expectedPerms = permittedPermissions[systemRelativePath]
				else:
					# Okay, no directive in svn to allow these file permissions to differ.
					fileres.expectedPerms = statexp.st_mode
				fileres.actualPerms   = tgtstat.st_mode
				if fileres.expectedPerms != fileres.actualPerms:
					res.changedpermissions.append(fileres)

				# and any ownership changes.
				if systemRelativePath in permittedOwnership:
					# OK, get from svn
					fileres.expecteduid = permittedOwnership[systemRelativePath].uid
					fileres.expectedgid = permittedOwnership[systemRelativePath].gid
				else:
					# Okay, no directive in svn to allow these file permissions to differ.
					fileres.expecteduid = statexp.st_uid
					fileres.expectedgid = statexp.st_gid
				fileres.actualuid = tgtstat.st_uid
				fileres.actualgid = tgtstat.st_gid
				if (fileres.actualuid != fileres.expecteduid or
				    fileres.actualgid != fileres.expectedgid   ):
					res.changedownership.append(fileres)

class auditThread(Thread):
	def __init__(self, val):
		Thread.__init__(self)
		self.val = val

	def run(self):
		global globalRes
		client = pysvn.Client()
		svnwd = tempfile.mkdtemp()
		client.checkout(repopath, svnwd)
		systemsvnpath = os.path.join(svnwd, targetname)
		if not (os.path.isdir(systemsvnpath)):
			print 'Creating config for new system %s' % targetname
			os.mkdir(systemsvnpath)
			client.add(systemsvnpath)
			client.checkin([systemsvnpath], ('Add new system %s' % targetname) )

		res = verifyAllFiles(systemsvnpath);
		globalRes = res

		global globalfinished
		globalfinished = True

		return

	def plsdie(self):
		global globalplsdie
		globalplsdie = True

def unhandled_input(key):
	if key in ('q', 'Q'):
		raise urwid.ExitMainLoop()


loop = None
def callback(self, user_data):
	if globalfinished:
		raise urwid.ExitMainLoop()
	else:
		if pbar != None:
			pbar.current = globalAuditProgress
		loop.set_alarm_in(1, callback)
		global lastdeb
		if txtLastDeb != None:
			txtLastDeb.set_text( globallastdeb );
	

palette=[ 	
		('title', 'white', 'dark red'), 
	    	('streak', 'black', 'dark red'),
	    	('bg', 'black', 'dark blue'),
	    	('pg normal', 'white', 'black', 'standout'),
	    	('pg complete', 'white', 'dark magenta'),
		('progressText', 'black', 'dark red'),
		('menu', 'black', 'light gray'),
		('menuTitle', 'black', 'dark red')
	]

def makeUnthemedButton(caption, clickHandler, clickHandlerArgs):
	button = urwid.Button( caption )
	if clickHandler != None:
		urwid.connect_signal(button, 'click', clickHandler, clickHandlerArgs)
	return button

def themeButton(button):
	return urwid.AttrMap(button, None, focus_map='reversed')

def makeButton(caption, clickHandler, clickHandlerArgs):
	b = makeUnthemedButton(caption, clickHandler, clickHandlerArgs)
	b = themeButton(b)
	return b

def makeMenu(caption, items):
	# Add menu title and diver to items list
	menuTitleText = urwid.Text(caption, align='center')
	menuTitleTextMap = urwid.AttrMap(menuTitleText, 'menuTitle')
	options = list()
	options.append(menuTitleTextMap)
	options.append(urwid.Divider())
	# Now add all the itesm we want
	for item in items:
		options.append(item)
	# and make our list box.
	lst = urwid.ListBox(urwid.SimpleFocusListWalker(options))
	map = urwid.AttrMap(lst, 'menu')
	return map

def makeMenuItemList(caption):
	menuTitleText = urwid.Text(caption, align='center')
	menuTitleTextMap = urwid.AttrMap(menuTitleText, 'menuTitle')

	return options

def makebackgroundwidgets():
	title = urwid.Text( ('title', u"Linux-mode audit script"))
	map1 = urwid.AttrMap(title, 'streak')
	fill1 = urwid.Filler(map1, 'top')
	mapTitle = urwid.AttrMap(fill1, 'bg')

	return mapTitle

def doAuditCurses():
	# The progress-bar auditing window
	global pbar
	global txtLastDeb

	# todo: replace with call to makebackgroundwidgets
	title = urwid.Text( ('title', u"Linux-mode audit script"))
	map1 = urwid.AttrMap(title, 'streak')
	fill1 = urwid.Filler(map1, 'top')
	mapTitle = urwid.AttrMap(fill1, 'bg')

	pbar = urwid.ProgressBar('pg normal', 'pg complete' )
	fill2 = urwid.Filler(pbar)
	mapProgress = urwid.AttrMap(fill2, 'bg')

	txtLastDeb = urwid.Text( ('progressText', "..") )
	map3 = urwid.AttrMap(txtLastDeb, 'progressText')
	fill3 = urwid.Filler(map3, 'top')
	mapLastDeb = urwid.AttrMap(fill3, 'bg')

	pile = urwid.Pile([mapTitle, mapProgress, mapLastDeb])

	global loop
	loop = urwid.MainLoop(pile, palette, unhandled_input=unhandled_input)
	loop.set_alarm_in(1, callback)

	myauditthread = auditThread(1)
	myauditthread.start()

	loop.run()

	myauditthread.plsdie()

class uidata:
	# Our main pad
	mainPad = None
	# Child menus
	mainMenu = None
	l2button = None		# The button we clicked to get here
	l1Menu = None
	l2Menu = None
	# Controls
	commitButton = None	# The main menu's "commit pending files to SVN"
	# SVN stuff
	thingsToCheckIn = list()
	client = None
	systemsvnpath = None
	extraFilesToCheck = list()
ui = uidata()	

def doMissingFileInfo(button, file):
	global ui
	items = list()
	items.append( urwid.Text('Package %s version %s' % (file.pkg.name, file.pkg.ver,) ) )
	items.append( urwid.Text('File %s' % file.filename) )
	items.append( makeButton('Restore file to target', restoreToTargetCurses, file ) )
	items.append( makeButton('Permit file to be missing', addMissingFile, file ) )
	items.append( makeButton('Purge package from target', purgepkg, file.pkg ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Missing file info', items);
	pile = urwid.Pile( [lst] )

	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def doInfo(button, file):
	global ui
	items = list()
	items.append( urwid.Text('Package %s version %s' % (file.pkg.name, file.pkg.ver,) ) )
	items.append( urwid.Text('File %s' % file.filename) )
	items.append( makeButton('Show diff of file', showDiffCurses, file ) )
	items.append( makeButton('Show unified diff of file', showUniDiffCurses, file ) )
	items.append( makeButton('Edit file on target systen', shellToEditor, file ) )
	items.append( makeButton('Restore file to target', restoreToTargetCurses, file ) )
#	items.append( makeButton('Commit file to SVN', addToSVNCommitList, file.filename ) )
	items.append( makeButton('Commit file to SVN', commit, file ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Failed file info', items);
	pile = urwid.Pile( [lst] )
	
	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def doExtraFileInfo(button, file):
	global ui
	items = list()
	items.append( urwid.Text('File %s' % file) )
	items.append( makeButton('Delete file from target', deleteFromTargetCurses, file ) )
	items.append( makeButton('Commit file to SVN', addToSVNCommitList, file ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Failed file info', items);
	pile = urwid.Pile( [lst] )

	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def doBadPermsInfo(button, file):
	global ui
	items = list()
	items.append( urwid.Text('Package %s version %s' % (file.pkg.name, file.pkg.ver,) ) )
	items.append( urwid.Text('File %s' % file.filename) )
	items.append( makeButton('Restore file to original permissions', restorePermsCurses, file ) )
	items.append( makeButton('Permit file to have modified permissions', addPermsFile, file ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Failed permissions file info', items);
	pile = urwid.Pile( [lst] )

	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def doBadOwnsInfo(button, file):
	global ui
	items = list()
	items.append( urwid.Text('Package %s version %s' % (file.pkg.name, file.pkg.ver,) ) )
	items.append( urwid.Text('File %s' % file.filename) )
	items.append( urwid.Text('Owner %d, expected %d' % (file.actualuid, file.expecteduid,) ) )
	items.append( urwid.Text('Group %d, expected %d' % (file.actualgid, file.expectedgid,) ) )
	items.append( makeButton('Restore file to original ownership', restoreOwnsCurses, file ) )
	items.append( makeButton('Permit file to have modified ownership', addOwnsFile, file ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Failed ownership file info', items);
	pile = urwid.Pile( [lst] )

	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def doBadPkgInfo(button, pkg):
	global ui
	items = list()
	items.append( urwid.Text('Package %s version %s' % (pkg.name, pkg.ver,) ) )
	items.append( makeButton('Purge file from target', purgepkg, pkg ) )
	items.append( makeButton('OK', returnToL1Menu, None ) )

	lst = makeMenu('Failed package', items);
	pile = urwid.Pile( [lst] )

	ui.l2button = button

	ui.l2Menu = pile
	ui.mainPad.original_widget = pile

def addMissingFile(button, file):
	addFile(ui.missingfilessvnpath, file.filename)
	ui.l2button.set_label( ('[permitted] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def addPermsFile(button, file):
	if ',' in file.filename:
		raise 'no commas in filenames pls'
	line = ('%s,%d' % (file.filename,file.actualPerms ,) )
	addFile(ui.modifiedpermssvnpath, line)
	ui.l2button.set_label( ('[permitted] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def addOwnsFile(button, file):
	if ',' in file.filename:
		raise 'no commas in filenames pls'
	line = ('%s,%d,%d' % (file.filename, file.actualuid, file.actualgid,) )
	addFile(ui.modifiedownershipsvnpath, line)
	ui.l2button.set_label( ('[permitted] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def addFile(fileToAddTo, lineToAdd):
	# Add a file entry to our 'permitted missing' list
	with open(fileToAddTo, 'a') as myfile:
		myfile.write('%s\n' % lineToAdd)

	if not fileToAddTo in ui.thingsToCheckIn:
		ui.thingsToCheckIn.append(fileToAddTo)

def showFailed(button, res):
	doFileList('Failed files', res.badfiles, doInfo)

def showMissing(button, res):
	doFileList('Files missing from target', res.missingfiles, doMissingFileInfo)

def showExtraFiles(button, res):
	global ui

	files = list()
	for file in res.extrafiles:
		files.append( makeButton(file, doExtraFileInfo, file ) )

	files.append( urwid.Divider() )
	files.append( makeButton('OK', returnToMainMenu, None) )

	lst = makeMenu('Unexpected files', files);
	pileFailed = urwid.Pile( [lst] )

	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def showBadPerms(button, res):
	global ui

	files = list()
	for file in res.changedpermissions:
		caption = '%s: expected %o actual %o' % (file.filename, file.expectedPerms, file.actualPerms )
		files.append( makeButton(caption, doBadPermsInfo, file ) )

	files.append( urwid.Divider() )
	files.append( makeButton('OK', returnToMainMenu, None) )

	lst = makeMenu('Files with modified permissions', files);
	pileFailed = urwid.Pile( [lst] )

	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def showBadOwnership(button, res):
	global ui

	files = list()
	for file in res.changedownership:
		caption = '%s: expected %d:%d actual %d:%d' % (file.filename, 
			file.expecteduid, file.expectedgid, file.actualuid, file.actualgid )
		files.append( makeButton(caption, doBadOwnsInfo, file ) )

	files.append( urwid.Divider() )
	files.append( makeButton('OK', returnToMainMenu, None) )

	lst = makeMenu('Files with modified ownership', files);
	pileFailed = urwid.Pile( [lst] )

	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def showBadPkgs(button, res):
	global ui

	files = list()
	for pkg in res.badpackages:
		caption = '%s ver %s' % (pkg.name, pkg.ver) 
		files.append( makeButton(caption, doBadPkgInfo, pkg ) )

	files.append( urwid.Divider() )
	files.append( makeButton('OK', returnToMainMenu, None) )

	lst = makeMenu('Packages we could not verify', files);
	pileFailed = urwid.Pile( [lst] )

	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def doFileList(menuCaption, collection, handler):
	global ui

	files = list()
	for file in collection:
		caption = '(%s) %s' % (file.pkg.name, file.filename, )
		files.append( makeButton(caption, handler, file ) )

	files.append( urwid.Divider() )
	files.append( makeButton('OK', returnToMainMenu, None) )

	lst = makeMenu(menuCaption, files);
	pileFailed = urwid.Pile( [lst] )

	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def returnToMainMenu(button):
	global ui
	ui.mainPad.original_widget = ui.mainMenu

def returnToL1Menu(button):
	global ui
	ui.mainPad.original_widget = ui.l1Menu

def returnToL2Menu(button):
	global ui
	ui.mainPad.original_widget = ui.l2Menu

def showDiffCurses(button, pkg):
	showMaybeUniDiffCurses(button, pkg, False)

def showUniDiffCurses(button, pkg):
	showMaybeUniDiffCurses(button, pkg, True)

def showMaybeUniDiffCurses(button, pkg, isUnified):
	global ui
	diffText = doDiff(pkg, isUnified);

	# Add each line as a seperate text field
	controls = list()
	for line in diffText.splitlines():
		controls.append(  urwid.Text(str(line))  )

	controls.append( makeButton('OK', returnToL2Menu, None) )

	caption = 'Diff of file %s' % pkg.filename
	lst = makeMenu(caption, controls)

	ui.mainPad.original_widget = lst

def restoreToTargetCurses(button, pkg):
	global ui
	if (pkg == fakePkg):
		return
	restoreToTarget(pkg)
	ui.l2button.set_label( ('[restored] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def restorePermsCurses(button, pkg):
	global ui
	filename = os.path.join(targetroot, pkg.filename)
	os.chmod(filename, pkg.expectedPerms)
	ui.l2button.set_label( ('[restored] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def restoreOwnsCurses(button, pkg):
	global ui
	filename = os.path.join(targetroot, pkg.filename)
	os.chown(filename, pkg.expecteduid, pkg.expectedgid)
	ui.l2button.set_label( ('[restored] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def purgepkg(button, pkg):
	global ui
	subprocess.call( ['dpkg', '--root', targetroot, '--purge', pkg.name   ] )
	ui.l2button.set_label( ('[purged] %s' % ui.l2button.get_label()) )
	# TODO: Again, we need to force a refresh

def deleteFromTargetCurses(button, filename):
	global ui
	os.remove(filename)
	ui.l2button.set_label( ('[deleted] %s' % ui.l2button.get_label()) )
	returnToL1Menu(None)

def shellToEditor(button, pkg):
	global ui
	filename = os.path.join(targetroot, pkg.filename)
	subprocess.call( [editor, filename  ] )
	# TODO: We need to force a screen refresh now that the editor has exited. 
	# The following doesn't work, though.
	#ui.loop.set_alarm_in(1, refresh)

def commit(button, pkg):
	addToSVNCommitList(button, pkg.filename)

def addToSVNCommitList(button, file):
	tgtfile = os.path.join(targetroot, file)
	if (os.path.isdir(tgtfile) and not os.path.islink(tgtfile)):
		modified = addDirsToSVNCommitList(file.split(os.path.sep))
	else:
		modified = addFileToSVNCommitList(button, file)

	for component in modified:
		ui.thingsToCheckIn.append(component)

	# Update the main menu's commit button text
	ui.commitButton.set_label( 'Commit pending changes to SVN (%d pending)' % (len(ui.thingsToCheckIn) ) )
	ui.l2button.set_label( ('[committed] %s' % ui.l2button.get_label()) )

	returnToL1Menu(None)

def addDirsToSVNCommitList(pathcomponents):
	global ui
	toret = list()
	createdSoFar = ui.systemsvnpath;
	for dir in pathcomponents:
		svndirpath = os.path.join(createdSoFar, dir)
		if not os.path.isdir(svndirpath):
			os.mkdir(svndirpath)
			ui.client.add(svndirpath)
			toret.append(svndirpath)
		createdSoFar = os.path.join(createdSoFar, dir)

	return toret

def addFileToSVNCommitList(button, file):
	# We'll need to make the directory stucture first, if it doesn't already exist.
	pathcomponents = file.split(os.path.sep)[:-1]
	tocommit = addDirsToSVNCommitList(pathcomponents)
	# Now add the new file, or update it if it already exists.
	svnfilepath = os.path.join(ui.systemsvnpath, file)
	if ( os.path.isfile(svnfilepath) or os.path.islink(svnfilepath)  ):
		isNewFile = False
	else:
		isNewFile = True

	srcfilepath = os.path.join(targetroot, file)
	print srcfilepath
	if os.path.islink(srcfilepath):
		# It's a symlink. Make a new one.
		linkto = os.readlink(srcfilepath)
		print svnfilepath
#		print 'is link to %s' % linkto
		os.symlink(linkto, svnfilepath)
	else:
		# Copy the file
	#	print '%s vs %s' % (srcfilepath, svnfilepath,)
	#	print ui.systemsvnpath
	#	os.exit()
		shutil.copyfile(srcfilepath, svnfilepath)

#	shutil.copy(srcfilepath, svnfilepath)
	if (isNewFile):
		ui.client.add(svnfilepath)

	tocommit.append(svnfilepath)

	return tocommit

def confirmCommitChangesToSvn(button):
	global ui

	controls = list()
	for file in ui.thingsToCheckIn:
		controls.append( urwid.Text(file) )

	controls.append( makeButton('Commit', getCommitMessageAndCommit, None)  )
	controls.append( makeButton('Cancel', returnToMainMenu, None)  )

	lst = makeMenu('Pending files to commit:', controls)
	pileFailed = urwid.Pile( [lst] )
	ui.l1Menu = pileFailed
	ui.mainPad.original_widget = pileFailed

def getCommitMessageAndCommit(button):
	global ui
	# Ask the user for a commit message
	ui.commitMsgBox = urwid.Edit("Please provide commit message: ")
	fill = questionBox(ui.commitMsgBox)
	ui.l1Menu = fill
	ui.mainPad.original_widget = fill

class questionBox(urwid.Filler):
	def keypress(self, size, key):
		if key != 'enter':
			return super(questionBox, self).keypress(size, key)
		commitChangesToSVN(ui.commitMsgBox.edit_text)
		returnToMainMenu(None);

def commitChangesToSVN(commitmsg):
	global ui
	ui.client.checkin(ui.thingsToCheckIn, commitmsg )
	ui.thingsToCheckIn = list()
	# Revert the main menu's commit button text
	ui.commitButton.set_label( 'Commit pending changes to SVN' )
	
def doReportCurses():
	global globalRes
	global pad

	global ui

	# Things we want on our main menu
	options = list()
	options.append( makeButton( ('Failed files (%d)' % len(globalRes.badfiles)), showFailed, globalRes)		 )
	options.append( makeButton( ('Missing files (%d)' % len(globalRes.missingfiles)), showMissing, globalRes) 	 )
	options.append( makeButton( ('Changed permissions (%d)' % len(globalRes.changedpermissions)), showBadPerms, globalRes))
	options.append( makeButton( ('Changed ownership (%d)' % len(globalRes.changedownership)), showBadOwnership, globalRes))
	options.append( makeButton( ('Unverifiable packages (%d)' % len(globalRes.badpackages)), showBadPkgs, globalRes) )
	options.append( makeButton( ('Extra files (%d)' % len(globalRes.extrafiles)), showExtraFiles, globalRes) )

	# Keep a reference to this button so we can change its caption when we have files to commit
	ui.commitButton = makeUnthemedButton( 'Commit pending changes to SVN', confirmCommitChangesToSvn, None)
	options.append(themeButton(ui.commitButton))

	# Make our list
	map1 = makeMenu('Main menu', options)
	ui.mainPad = urwid.Padding(map1)
	
	# Make the background, and place our menu in an overlay in it
	bg = makebackgroundwidgets()
	top = urwid.Overlay(ui.mainPad, 
		bg,
		align='center', 
		width=('relative',70),
		valign='middle', 
		height=('relative',70),
		min_width=20, 
		min_height=9)
	ui.mainMenu = ui.mainPad.original_widget

	# Now... go!
	ui.loop = urwid.MainLoop(top, palette, unhandled_input=unhandled_input)
	ui.loop.run()

# Check cmdline args
usage = 'Usage: audit-linux.py <configfile> [--quiet]'
isQuiet = False
if len(sys.argv) < 2:
	raise Exception(usage)
else:
	i = importlib.import_module(sys.argv[1])
	targetname = i.targetname
	targetroot = i.targetroot
	archstr = i.archstr
	repopath = i.repopath
	editor = i.editor
	bootsectors = i.bootsectors
	
if len(sys.argv) > 2:
	if (sys.argv[2] == '--quiet'):
		isQuiet = True
	else:
		raise Exception(usage)

# Open the svn repo
ui.client = pysvn.Client()
svnwd = tempfile.mkdtemp()
ui.client.checkout(repopath, svnwd)
ui.systemsvnpath = os.path.join(svnwd, targetname)
if not (os.path.isdir(ui.systemsvnpath)):
	print 'Creating config for new system %s' % targetname
	os.mkdir(ui.systemsvnpath)
	ui.client.add(ui.systemsvnpath)
	ui.client.checkin([ui.systemsvnpath], ('Add new system %s' % targetname) )
# Create any needed config files
ui.missingfilessvnpath = ui.systemsvnpath + '_missingFiles'
ui.modifiedpermssvnpath = ui.systemsvnpath + '_modifiedPerms'
ui.modifiedownershipsvnpath = ui.systemsvnpath + '_modifiedOwnership'
# This last one is an edge case, meant to cover a situation wherein a file is replaced with a directory of the same name.
commitNeeded = False
for neededfile in [ ui.missingfilessvnpath, ui.modifiedpermssvnpath, ui.modifiedownershipsvnpath ]:
	if not (os.path.isfile(neededfile)):
		open(neededfile, 'a').close()
		ui.client.add(neededfile)
		commitNeeded = True
if commitNeeded:
	ui.client.checkin([ui.missingfilessvnpath], ('Add config files for system %s' % targetname) )

# (re)create boot sector information files
for devName in bootsectors:
	print devName
for devName in bootsectors:
	destFileName = 'boot-%s' % (devName,)
	if os.path.exists(destFileName):
		os.remove(destFileName)
	srcFileName = '/dev/%s' % devName
	with  open(srcFileName, 'rb') as f:
		sector = f.read(512)
	with open(destFileName, 'wb') as f:
		f.write(sector)
	ui.extraFilesToCheck.append(destFileName)

globalRes = auditresult()
doAuditCurses()

if isQuiet:
	globalRes.printResults()
	if (	(len(globalRes.badfiles) == 0) and
		(len(globalRes.missingfiles) == 0) and
		(len(globalRes.changedpermissions) == 0) and
		(len(globalRes.changedownership) == 0) and
		(len(globalRes.badpackages) == 0) and
		(len(globalRes.extrafiles) ==0)	):
		exit(0)
	else:	
		exit(-1)
else:
	doReportCurses()


