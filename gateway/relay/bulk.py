"""Literal placeholders only: no attribute access, indexing or format expressions."""
import re
import string
from pydantic import BaseModel, ConfigDict, Field, field_validator

PHONE = re.compile(r'^\+[1-9][0-9]{7,14}$')
FIELD = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')

def render(template,users):
    tokens=list(string.Formatter().parse(template))
    if any(name is not None and (not FIELD.fullmatch(name) or spec or conversion) for _,name,spec,conversion in tokens):
        raise ValueError('Only simple placeholders are supported')
    result=[]
    for user in users:
        text=''.join(literal+(user[name] if name is not None else '') for literal,name,_,_ in tokens)
        if not 1<=len(text)<=1600 or not text.strip() or any((ord(c)<32 and c not in '\n\r\t') or 0xD800<=ord(c)<=0xDFFF for c in text):
            raise ValueError('Invalid rendered text')
        result.append((user['phone'],text))
    return result

class BulkMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    template: str = Field(min_length=1,max_length=1600)
    users: list[dict[str,str]] = Field(min_length=1,max_length=1000)
    device_id: str = Field('auto',pattern=r'^[A-Za-z0-9_-]{1,64}$')

    @field_validator('users')
    @classmethod
    def valid_users(cls,users):
        for user in users:
            if len(user)>33 or not PHONE.fullmatch(user.get('phone','')) or any(not FIELD.fullmatch(k) or len(v)>1600 for k,v in user.items()):
                raise ValueError('Invalid user')
        return users

    @field_validator('template')
    @classmethod
    def valid_template(cls,value):
        try:
            tokens=list(string.Formatter().parse(value))
            if any(name is not None and (not FIELD.fullmatch(name) or spec or conversion) for _,name,spec,conversion in tokens): raise ValueError()
        except ValueError:
            raise ValueError('Invalid template') from None
        return value
