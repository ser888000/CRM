import io
from collections import defaultdict
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required,permission_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import FileResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from .models import LibraryEntry,LibraryAttachment,normalize_location
from .legacy_library import load_package,apply_package,LibraryImportError,MAX_PACKAGE

class LibrarySearch(forms.Form):
    q=forms.CharField(label='Поиск в библиотеке',required=False,max_length=250)

@login_required
@permission_required('crm.view_libraryentry',raise_exception=True)
@never_cache
def browse(request,pk=None):
    form=LibrarySearch(request.GET);query=''
    selected=get_object_or_404(LibraryEntry,pk=pk) if pk else None
    qs=LibraryEntry.objects.defer('original_data','body','search_text').order_by('sort_order','pk')
    nodes=list(qs);count=len(nodes);lookup={v.pk:v for v in nodes};rows=[]
    if form.is_valid():query=form.cleaned_data['q']
    if query:
        matches=qs.filter(search_text__contains=normalize_location(query))
        rows=[{'entry':v,'indent':10} for v in matches]
    else:
        children=defaultdict(list)
        for node in nodes:children[node.parent_id if node.parent_id in lookup else None].append(node)
        seen=set();stack=[(n,0) for n in reversed(children[None])]
        while stack:
            node,depth=stack.pop()
            if node.pk in seen:continue
            seen.add(node.pk);rows.append({'entry':node,'indent':10+min(depth,12)*14})
            stack.extend((n,depth+1) for n in reversed(children[node.pk]))
        rows.extend({'entry':n,'indent':10} for n in nodes if n.pk not in seen)
    ancestors=[]
    if selected:
        seen={selected.pk};parent=selected.parent_id
        while parent in lookup and parent not in seen:
            seen.add(parent);node=lookup[parent];ancestors.insert(0,node);parent=node.parent_id
    files=selected.attachments.defer('data') if selected else []
    return render(request,'crm/library.html',{'search':form,'query':query,'tree_rows':rows,'entry':selected,'ancestors':ancestors,'files':files,'count':count})

class LibraryPackageForm(forms.Form):
    package=forms.FileField(label='Подготовленный ZIP библиотеки',widget=forms.FileInput(attrs={'accept':'.zip'}))
    def clean_package(self):
        value=self.cleaned_data['package']
        if value.size>MAX_PACKAGE:raise forms.ValidationError('Максимальный размер пакета — 8 МБ.')
        return value

@login_required
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def import_library(request):
    if not request.user.is_active or not request.user.is_superuser:raise PermissionDenied
    form=LibraryPackageForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:
            package=load_package(form.cleaned_data['package']);run,created=apply_package(package,request.user)
        except LibraryImportError as error:form.add_error('package',str(error))
        except IntegrityError:form.add_error(None,'Данные уже изменились в другом окне. Обновите страницу и проверьте библиотеку.')
        else:
            messages.success(request,f"Загружено разделов: {run.summary['entries']}, файлов: {run.summary['files']}." if created else 'Этот пакет уже загружен. Дубликаты не созданы.')
            if run.issues:messages.warning(request,f'Есть замечания к исходным данным: {len(run.issues)}. Оригиналы сохранены.')
            return redirect('library')
    return render(request,'crm/library_import.html',{'form':form})

@login_required
@permission_required('crm.view_libraryentry',raise_exception=True)
@never_cache
def download_file(request,pk):
    file=get_object_or_404(LibraryAttachment,pk=pk)
    response=FileResponse(io.BytesIO(bytes(file.data)),as_attachment=True,filename=file.original_name,content_type='application/octet-stream')
    response['X-Content-Type-Options']='nosniff';return response

@login_required
@permission_required('crm.view_libraryentry',raise_exception=True)
@never_cache
def original(request,pk):
    entry=get_object_or_404(LibraryEntry,pk=pk)
    extension='rtf' if entry.original_format=='rtf' else 'txt'
    response=FileResponse(io.BytesIO(bytes(entry.original_data)),as_attachment=True,filename=f'library-{entry.source_id or entry.pk}.{extension}',content_type='application/octet-stream')
    response['X-Content-Type-Options']='nosniff';return response
