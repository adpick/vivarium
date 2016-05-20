import numpy as np
import pandas as pd

def sort_modules(to_sort, modules_registry):
    def inner_sort(sorted_modules, current):
        if not current.DEPENDENCIES:
            return [current] + sorted_modules
        else:
            i = 0
            for dependency in current.DEPENDENCIES:
                try:
                    i = max(i, sorted_modules.index(modules_registry[dependency]))
                except ValueError:
                    sorted_modules = inner_sort(sorted_modules, modules, modules_registry[dependency])
                    i = max(i, sorted_modules.index(modules_registry[dependency]))
            return sorted_modules[0:i+1] + [current] + sorted_modules[i+1:]

    to_sort = set(to_sort)
    sorted_modules = []
    while to_sort.difference(sorted_modules):
        current = to_sort.pop()
        sorted_modules = inner_sort(sorted_modules, current)
    return sorted_modules

def from_yearly_rate(rate, time_step):
    return rate * (time_step.total_seconds() / (60*60*24*365.0))

def to_yearly_rate(rate, time_step):
    return rate / (time_step.total_seconds() / (60*60*24*365.0))

def rate_to_probability(rate):
    return 1-np.exp(-rate)

def mask_for_rate(population, rate):
    population = population.join(pd.DataFrame(np.random.random(size=len(population)), columns=['draw']))
    population['probability'] = rate_to_probability(rate)
    return population.draw < population.probability

# _MethodDecoratorAdaptor and auto_adapt_to_methods from http://stackoverflow.com/questions/1288498/using-the-same-decorator-with-arguments-with-functions-and-methods
class _MethodDecoratorAdaptor(object):
    def __init__(self, decorator, func):
        self.decorator = decorator
        self.func = func
    def __call__(self, *args, **kwargs):
        return self.decorator(self.func)(*args, **kwargs)
    def __get__(self, instance, owner):
        return self.decorator(self.func.__get__(instance, owner))

def auto_adapt_to_methods(decorator):
    """Allows you to use the same decorator on methods and functions,
    hiding the self argument from the decorator."""
    def adapt(func):
        return _MethodDecoratorAdaptor(decorator, func)
    return adapt

@auto_adapt_to_methods
def only_living(fun):
    def inner(label, mask, simulation):
            return fun(label, mask & (simulation.population.alive == True), simulation)
    return inner
