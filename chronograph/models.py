# -*- encoding: utf-8 -*-
from django.db import models
from django.utils.timesince import timeuntil
from django.utils.translation import ungettext, ugettext, ugettext_lazy as _
from django.template import loader, Context
from django.conf import settings
from django.utils.encoding import smart_str

import os
import sys
import traceback
from datetime import datetime
from dateutil import rrule
from StringIO import StringIO

class JobManager(models.Manager):
    def due(self):
        """
        Returns a ``QuerySet`` of all jobs waiting to be run.
        """
        return self.filter(next_run__lte=datetime.now(), disabled=False, is_running=False)

# A lot of rrule stuff is from django-schedule
freqs = (   ("YEARLY", _(u"Nunca")),
            ("MONTHLY", _(u"Cada mes")),
            ("WEEKLY", _(u"Cada semana")),
            ("DAILY", _(u"Cada día")),
            ("HOURLY", _(u"Cada hora")),
            ("MINUTELY", _(u"Cada minuto")),
            ("SECONDLY", _(u"Cada segundo")))

class Job(models.Model):
    """
    A recurring ``django-admin`` command to be run.
    """
    name = models.CharField(_("name"), max_length=200)
    frequency = models.CharField(_("Frecuencia"), choices=freqs, max_length=10)
    params = models.TextField(_("params"), null=True, blank=True,
        help_text=_('Comma-separated list of <a href="http://labix.org/python-dateutil" target="_blank">rrule parameters</a>. e.g: interval:15'))
    command = models.CharField(_("Comando"), max_length=200,
        help_text=_("A valid django-admin command to run."), blank=True)
    args = models.CharField(_("args"), max_length=200, blank=True,
        help_text=_("Space separated list; e.g: arg1 option1=True"))
    disabled = models.BooleanField(_(u'Deshabilitado'), default=False)
    next_run = models.DateTimeField(_(u"Próxima ejecución"), blank=True, null=True,
                                    help_text=_(u"Si deja este campo vacío se"
                                                u" establecerá automáticamente"))
    last_run = models.DateTimeField(_("last run"), editable=False, blank=True, null=True)
    is_running = models.BooleanField(default=False, editable=False)
    
    objects = JobManager()
    
    class Meta:
        ordering = ('disabled', 'next_run',)
        verbose_name = _(u'Tarea')
        verbose_name_plural = _(u'Tareas')
    
    def __unicode__(self):
        if self.disabled:
            return _(u"%(name)s - disabled") % {'name': self.name}
        return u"%s - %s" % (self.name, self.timeuntil)
    
    def save(self, force_insert=False, force_update=False):
        if not self.disabled:
            if not self.last_run:
                self.last_run = datetime.now()
            if not self.next_run:
                self.next_run = self.rrule.after(self.last_run)
        else:
            self.next_run = None
        
        super(Job, self).save(force_insert, force_update)

    def get_timeuntil(self):
        """
        Returns a string representing the time until the next
        time this Job will be run.
        """
        if self.disabled:
            return _('never (disabled)')
        
        delta = self.next_run - datetime.now()
        if delta.days < 0:
            # The job is past due and should be run as soon as possible
            return _('due')
        elif delta.seconds < 60:
            # Adapted from django.utils.timesince
            count = lambda n: ungettext('second', 'seconds', n)
            return ugettext('%(number)d %(type)s') % {'number': delta.seconds,
                                                      'type': count(delta.seconds)}
        return timeuntil(self.next_run)
    get_timeuntil.short_description = _('time until next run')
    timeuntil = property(get_timeuntil)
    
    def get_rrule(self):
        """
        Returns the rrule objects for this Job.
        """
        frequency = eval('rrule.%s' % self.frequency)
        return rrule.rrule(frequency, dtstart=self.last_run, **self.get_params())
    rrule = property(get_rrule)
    
    def get_params(self):
        """
        >>> job = Job(params = "count:1;bysecond:1;byminute:1,2,4,5")
        >>> job.get_params()
        {'count': 1, 'byminute': [1, 2, 4, 5], 'bysecond': 1}
        """
        if self.params is None:
            return {}
        params = self.params.split(';')
        param_dict = []
        for param in params:
            param = param.split(':')
            if len(param) == 2:
                param = (str(param[0]), [int(p) for p in param[1].split(',')])
                if len(param[1]) == 1:
                    param = (param[0], param[1][0])
                param_dict.append(param)
        return dict(param_dict)
    
    def get_args(self):
        """
        Processes the args and returns a tuple or (args, options) for passing to ``call_command``.
        """
        args = []
        options = {}
        # El primer argumento es automáticamente el ID de la propia instancia
        args.append(self.id)
        for arg in self.args.split():
            if arg.find('=') > -1:
                key, value = arg.split('=')
                options[smart_str(key)] = smart_str(value)
            else:
                args.append(arg)
        return (args, options)
    
    def run(self, save=True):
        """
        Runs this ``Job``.  If ``save`` is ``True`` the dates (``last_run`` and ``next_run``)
        are updated.  If ``save`` is ``False`` the job simply gets run and nothing changes.
        
        A ``Log`` will be created if there is any output from either stdout or stderr.
        """
        from django.core.management import call_command
        
        args, options = self.get_args()
        stdout = StringIO()
        stderr = StringIO()
        
        # Redirect output so that we can log it if there is any
        ostdout = sys.stdout
        ostderr = sys.stderr
        sys.stdout = stdout
        sys.stderr = stderr
        stdout_str, stderr_str = "", ""
        
        run_date = datetime.now()
        self.is_running = True
        self.save()
        try:
            call_command(self.command, *args, **options)
        except Exception, e:
            # The command failed to run; log the exception
            t = loader.get_template('chronograph/error_message.txt')
            c = Context({
              'exception': unicode(e),
              'traceback': ['\n'.join(traceback.format_exception(*sys.exc_info()))]
            })
            stderr_str += t.render(c)
        self.is_running = False
        self.save()
        
        if save:
            self.last_run = run_date
            self.next_run = self.rrule.after(run_date)
            self.save()
        
        # If we got any output, save it to the log
        stdout_str += stdout.getvalue()
        stderr_str += stderr.getvalue()
        if stdout_str or stderr_str:
            log = Log.objects.create(
                job = self,
                run_date = run_date,
                stdout = stdout_str,
                stderr = stderr_str
            )
        
        # Redirect output back to default
        sys.stdout = ostdout
        sys.stderr = ostderr
            

class Log(models.Model):
    """
    A record of stdout and stderr of a ``Job``.
    """
    job = models.ForeignKey(Job)
    run_date = models.DateTimeField(auto_now_add=True)
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
        
    class Meta:
        ordering = ('-run_date',)
        verbose_name = _(u'Registro')
        verbose_name_plural = _(u'Registros')
    
    def __unicode__(self):
        return u"%s - %s" % (self.job.name, self.run_date)
