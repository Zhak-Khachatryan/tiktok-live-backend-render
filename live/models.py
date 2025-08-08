
# Create your models here.

from django.db import models

class Donator(models.Model):
  username = models.CharField(max_length=100, unique=True)
  user_image = models.URLField(blank=True, null=True)
  diamonds = models.IntegerField(default=0)

  class Meta:
    ordering = ['-diamonds']

class Gift(models.Model):
  user = models.ForeignKey(Donator, on_delete=models.CASCADE, related_name='gifts')
  gift_name = models.CharField(max_length=100)
  gift_image = models.URLField(blank=True, null=True)
  gift_count = models.IntegerField(default=1)
  diamonds = models.IntegerField(default=0)
  timestamp = models.DateTimeField(auto_now_add=True)
  read = models.BooleanField(default=False)

  class Meta:
    ordering = ['timestamp']

  def __str__(self):
    return self.timestamp