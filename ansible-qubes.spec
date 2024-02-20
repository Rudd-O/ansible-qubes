%define debug_package %{nil}

%define mybuildnumber %{?build_number}%{?!build_number:1}

Name:           ansible-qubes
Version:        0.0.21
Release:        %{mybuildnumber}%{?dist}
Summary:        Inter-VM program execution for Qubes OS AppVMs and StandaloneVMs
BuildArch:      noarch

License:        GPLv3+
URL:            https://github.com/Rudd-O/ansible-qubes
Source0:        https://github.com/Rudd-O/%{name}/archive/{%version}.tar.gz#/%{name}-%{version}.tar.gz

BuildRequires:  make
BuildRequires:  gawk

Requires:       python3

%description
This package lets you execute programs between VMs as if it was SSH.

%prep
%setup -q

%build
# variables must be kept in sync with install
make DESTDIR=$RPM_BUILD_ROOT BINDIR=%{_bindir}

%install
rm -rf $RPM_BUILD_ROOT
# variables must be kept in sync with build
for target in install; do
    make $target DESTDIR=$RPM_BUILD_ROOT BINDIR=%{_bindir}
done

%files
%attr(0755, root, root) %{_bindir}/*
%doc README.md

%changelog
* Sun Jul 09 2017 Manuel Amador (Rudd-O) <rudd-o@rudd-o.com>
- Initial release.
