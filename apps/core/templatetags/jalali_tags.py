import jdatetime
from django import template
from datetime import datetime, date

register = template.Library()

@register.filter(name='to_jalali')
def to_jalali(value):
    if not value:
        return ''
    try:
        if isinstance(value, datetime):
            # Convert to local timezone first if timezone-aware
            # jdatetime handles aware datetimes or naive
            jd = jdatetime.datetime.fromgregorian(datetime=value)
            return jd.strftime('%Y/%m/%d - %H:%M')
        elif isinstance(value, date):
            jd = jdatetime.date.fromgregorian(date=value)
            return jd.strftime('%Y/%m/%d')
    except Exception:
        pass
    return value


@register.filter(name='get_stage_state')
def get_stage_state(application, stage):
    try:
        for state in application.stage_states.all():
            if state.stage_id == stage.id:
                return state
    except Exception:
        pass
    return None


@register.filter(name='get_item')
def get_item(dictionary, key):
    try:
        return dictionary.get(key)
    except Exception:
        return None


@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    d = context['request'].GET.copy()
    for k, v in kwargs.items():
        d[k] = v
    return d.urlencode()


@register.simple_tag(takes_context=True)
def sort_url(context, field):
    request = context['request']
    d = request.GET.copy()
    
    current_sort = d.get('sort', 'created_at')
    current_order = d.get('order', 'desc')
    
    if current_sort == field:
        new_order = 'desc' if current_order == 'asc' else 'asc'
    else:
        new_order = 'asc'
        
    d['sort'] = field
    d['order'] = new_order
    
    if 'page' in d:
        del d['page']
        
    return f"?{d.urlencode()}"

