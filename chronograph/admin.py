from django.contrib import admin
from django.db import models
from django import forms
from django.utils.translation import ungettext, ugettext_lazy as _
from django.http import HttpResponseRedirect, Http404
from django.conf.urls.defaults import patterns, url
from django.utils.safestring import mark_safe
from django.forms.util import flatatt
from django.utils.html import escape
from django.template.defaultfilters import linebreaks

from chronograph.models import Job, Log

class HTMLWidget(forms.Widget):
    def __init__(self,rel=None, attrs=None):
        self.rel = rel
        super(HTMLWidget, self).__init__(attrs)
    
    def render(self, name, value, attrs=None):
        if self.rel is not None:
            key = self.rel.get_related_field().name
            obj = self.rel.to._default_manager.get(**{key: value})
            related_url = '../../../%s/%s/%d/' % (self.rel.to._meta.app_label, self.rel.to._meta.object_name.lower(), value)
            value = "<a href='%s'>%s</a>" % (related_url, escape(obj))
            
        final_attrs = self.build_attrs(attrs, name=name)
        return mark_safe("<div%s>%s</div>" % (flatatt(final_attrs), linebreaks(value)))

class JobAdmin(admin.ModelAdmin):
    list_display = ('name', 'next_run', 'last_run', 'frequency', 'params', 'get_timeuntil', 'is_running')
    list_filter = ('frequency', 'disabled',)
    
    fieldsets = (
        (None, {
            'fields': ('name', ('command', 'args',), 'disabled',)
        }),
        ('Frequency options', {
            'classes': ('wide',),
            'fields': ('frequency', 'next_run', 'params',)
        }),
    )
    
    def run_job_view(self, request, pk):
        """
        Runs the specified job.
        """
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise Http404
        job.run(save=False)
        request.user.message_set.create(message=_('The job "%(job)s" was run successfully.') % {'job': job})        
        return HttpResponseRedirect(request.path + "../")
    
    def get_urls(self):
        urls = super(JobAdmin, self).get_urls()
        my_urls = patterns('',
            url(r'^(.+)/run/$', self.admin_site.admin_view(self.run_job_view), name="chronograph_job_run")
        )
        return my_urls + urls

class LogAdmin(admin.ModelAdmin):
    list_display = ('job_name', 'run_date',)
    search_fields = ('stdout', 'stderr', 'job__name', 'job__command')
    date_hierarchy = 'run_date'
    fieldsets = (
        (None, {
            'fields': ('job',)
        }),
        ('Output', {
            'fields': ('stdout', 'stderr',)
        }),
    )
    
    def job_name(self, obj):
      return obj.job.name
    job_name.short_description = _(u'Name')
    
    def has_add_permission(self, request):
        return False
    
    def formfield_for_dbfield(self, db_field, **kwargs):
        request = kwargs.pop("request", None)
        
        if isinstance(db_field, models.TextField):
            kwargs['widget'] = HTMLWidget()
            return db_field.formfield(**kwargs)
        
        if isinstance(db_field, models.ForeignKey):
            kwargs['widget'] = HTMLWidget(db_field.rel)
            return db_field.formfield(**kwargs)
        
        if isinstance(db_field, models.DateTimeField):
            print 'yup'
        
        return super(LogAdmin, self).formfield_for_dbfield(db_field, **kwargs)

admin.site.register(Job, JobAdmin)
admin.site.register(Log, LogAdmin)