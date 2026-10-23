# fuse🫖

Collection of FUSE drivers for technologies that support partially reading the contents of a file (e.g. through the [HTTP Range header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range)).

Modules available:
- [Artifactory](./fusetea/plugins/artifactory.py)
- [vCenter](./fusetea/plugins/vcenter.py)
- [Folder](./fusetea/plugins/folder.py): apache2 / nginx directory listings
- [File](./fusetea/plugins/file.py): a single file

## Installation

Grab a .deb from the [releases](https://github.com/synacktiv/fusetea/releases).

Or install it with pipx / uv. fusepy needs libfuse2, which you must install yourself (`apt install libfuse2t64`, or `libfuse2` on older releases):
```console
$ pipx install git+https://github.com/synacktiv/fusetea
$ uv tool install git+https://github.com/synacktiv/fusetea
```

## Artifactory

```console
$ fusetea artifactory https://artifactory.corp.local generic-local /tmp/output/
```

## vCenter

```console
$ fusetea vcenter https://vcenter.corp.local /tmp/output/ --user user@corp.local --password 'fus3t3a'
```

### Mounting LVM disks

Configure FUSE to allow other users to access mounted directories (useful to use qemu-nbd and other mounting tools needing privileges):
```console
# cat /etc/fuse.conf
user_allow_other
```

Install tools needed to mount the disk:
```console
# apt install lvm2 qemu-utils
```

Enable the `nbd` kernel module:
```console
# modprobe nbd
```

```console
# qemu-nbd -v -s -f vmdk -c /dev/nbd1 /tmp/output/Datacenter/default/sso/sso.vmdk
# lsblk # wait until you see the LVM
# mount -o ro --mkdir /dev/rl_sso/root /tmp/sso # mount -o ro --mkdir <logical_volume> <mountpoint>
```

The `-s` flag is required because LVMs will try to write data on the disk while mounting it: with this setting, `qemu-nbd` creates a temporary qcow2 file where these writes will be stored.

### Unmounting LVM disks

```console
# umount /tmp/sso
# lvchange -an rl_sso # lvchange -an <volume_group>
# qemu-nbd -d /dev/nbd1
```

## Folder

Mounts a directory listing served by apache2 or nginx (`autoindex`), the URL must point to the directory:

```console
$ fusetea folder https://files.corp.local/pub/ /tmp/output/
```

Subdirectories are browsed as well. Exact file sizes are fetched with a `HEAD` request the first time a file is accessed, as listings may only show approximate sizes (e.g. `1.2K`).

## File

Mounts a single file, the URL must point to the file. It is exposed at the root of the mount point with its name from the URL:

```console
$ fusetea file https://files.corp.local/pub/disk.vmdk /tmp/output/
$ ls /tmp/output/
disk.vmdk
```

### Authentication

Both `folder` and `file` support basic authentication and custom headers (`-H` can be repeated):

```console
$ fusetea folder https://files.corp.local/pub/ /tmp/output/ -u user -p 'fus3t3a'
$ fusetea file https://files.corp.local/pub/disk.vmdk /tmp/output/ -H 'Cookie: session=...' -H 'X-Api-Key: ...'
```
