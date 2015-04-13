This tool will audit a target Linux (debuan/ubuntu/etc) installation, by downloading .deb packages from the internet, validating their signatures, and comparing files. It should work with any apt-get/dpkg based distribution.

It will store changed files, along with extra files, in a specified subversion repository, for easy versioning.

It operates on an 'offline' installation - the idea is that it is booted from readonly media. It will download packages from the repositories specified sources.list as normal (a local mirror is advised for the impatient!)

It will also store drive boot sectors and verify them.

The usual workflow is to install and configure a machine, check in changes to SVN, and then use it for periodic auditing.

It takes a (python) configuration file for each host, for example:
	targetname = 'backup'

	bootsectors = [ 'sde', 'sde1' ]

	targetroot = '/mnt/target'

	archstr = 'i386'

	repopath= 'file:///root/syschanges'

	editor = 'nano'


'targetname' is a friendly name of the system, and 'repopath' is a repository path to pass to svn. 'targetroot' is the location that the system to audit is mounted at.
