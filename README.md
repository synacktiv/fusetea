# fuse🫖

Collection of FUSE drivers for technologies that support partially reading the contents of a file (e.g. through the [HTTP Range header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range)).

Modules available:
- [Artifactory](./fusetea/plugins/artifactory.py)
- [vCenter](./fusetea/plugins/vcenter.py)

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
