import os.path
from collections import defaultdict

import pandas as pd
import numpy as np

from ceam.util import sort_modules, from_yearly_rate, only_living, mask_for_rate

# Generic event handlers

def chronic_condition_incidence_handler(condition):
    @only_living
    def handler(label, mask, simulation):
        mask = mask & (simulation.population[condition] == False)
        incidence_rates = simulation.incidence_rates(simulation.population, condition)
        mask = mask & mask_for_rate(simulation.population, incidence_rates.incidence_rate)
        simulation.population.loc[mask, condition] = True
    return handler


class EventHandler(object):
    def __init__(self):
        super(EventHandler, self).__init__()
        self._listeners = defaultdict(set)
        self._generic_listeners = set()
        self._listener_priorities = {}

    def register_event_listener(self, listener, label=None, priority=10):
        assert callable(listener)
        if label:
            self._listeners[label].add(listener)
        else:
            self._generic_listeners.add(listener)
        self._listener_priorities[(label, listener)] = priority

    def deregister_event_listener(self, listener, label=None):
        if label:
            self._listeners[label].remove(listener)
        else:
            self._generic_listeners.remove(listener)
        del self._listener_priorities[(label, listener)]

    def emit_event(self, label, mask, simulation):
        listeners = [(self._listener_priorities[(label, listener)], listener) for listener in self._listeners[label]]
        listeners += [(self._listener_priorities[(None, listener)], listener) for listener in self._generic_listeners]
        listeners = [listener for _,listener in sorted(listeners, key=lambda x:x[0])]
        for listener in listeners:
            listener(label, mask.copy(), simulation)

class Simulation(object):
    def __init__(self):
        self.reference_data = {}
        self._modules = {}
        self._ordered_modules = []
        self.current_time = None
        self.yll_by_year = defaultdict(float)
        self.yld_by_year = defaultdict(float)
        self.deaths_by_year_and_cause = defaultdict(lambda: defaultdict(int))
        self.yll_by_year_and_cause = defaultdict(lambda: defaultdict(float))
        self.new_cases_per_year = defaultdict(lambda: defaultdict(int))
        self.register_module(BaseSimulationModule())
        self.population = pd.DataFrame

    def load_data(self, path_prefix):
        for module in self._ordered_modules:
            module.load_data(path_prefix)

    def load_population(self, path_prefix):
        #TODO: This will always be BaseSimulationModule which loads the core population definition and thus can discover what the population size is
        module = self._ordered_modules[0]
        module.load_population_columns(path_prefix, 0)
        population_size = len(module.population_columns)

        for module in self._ordered_modules[1:]:
            module.load_population_columns(path_prefix, population_size)
            assert module.population_columns.empty or len(module.population_columns) == population_size, 'Culpret: %s'%module
        self.reset_population()

    def reset_population(self):
        population = pd.DataFrame()
        for module in self._ordered_modules:
            population = population.join(module.population_columns, how='outer')
        self.population = population.join(pd.DataFrame(0, index=np.arange(len(population)), columns=['year']))

    def register_module(self, module):
        module.register(self)
        self._modules[module.__class__] = module

        # TODO: This little dance is awkward but it makes it so I can privilege BaseSimulationModule without having to import it in utils
        to_sort = set(self._modules.values())
        to_sort.remove(self._modules[BaseSimulationModule])
        self._ordered_modules = sort_modules(to_sort, self._modules)
        self._ordered_modules.insert(0, self._modules[BaseSimulationModule])

    def deregister_module(self, module):
        module.deregister(self)
        del self._modules[module.__class__]

        to_sort = set(self._modules.values())
        to_sort.remove(self._modules[BaseSimulationModule])
        self._ordered_modules = sort_modules(to_sort, self._modules)
        self._ordered_modules.insert(0, self._modules[BaseSimulationModule])

    def emit_event(self, label, mask):
        for module in self._ordered_modules:
            module.emit_event(label, mask, self)

    def mortality_rates(self, population):
        rates = pd.DataFrame(0, index=np.arange(len(population)), columns=['mortality_rate'])
        for module in self._ordered_modules:
            rates = module.mortality_rates(population, rates)
        return from_yearly_rate(rates, self.last_time_step)

    def incidence_rates(self, population, label):
        rates = pd.DataFrame(0, index=np.arange(len(population)), columns=['incidence_rate'])
        for module in self._ordered_modules:
            rates = module.incidence_rates(population, rates, label)
        return from_yearly_rate(rates, self.last_time_step)

    def years_lived_with_disability(self):
        ylds = 0
        for module in self._ordered_modules:
            ylds += module.years_lived_with_disability(self.population[self.population.alive == True])
        return ylds

    
    def run(self, start_time, end_time, time_step):
        self.current_time = start_time
        self.last_time_step = time_step
        while self.current_time <= end_time:
            self.population.year = self.current_time.year
            self.emit_event('time_step', np.array([True]*len(self.population)))
            self.yld_by_year[self.current_time.year] = self.years_lived_with_disability()
            self.current_time += time_step


    def reset(self):
        for module in self._ordered_modules:
            module.reset()
        self.reset_population()
        self.current_time = None
        self.yll_by_year = defaultdict(float)
        self.yld_by_year = defaultdict(float)
        self.deaths_by_year_and_cause = defaultdict(lambda: defaultdict(float))
        self.yll_by_year_and_cause = defaultdict(lambda: defaultdict(float))
        self.new_cases_per_year = defaultdict(lambda: defaultdict(int))

class SimulationModule(EventHandler):
    DEPENDENCIES = set()
    def __init__(self):
        EventHandler.__init__(self)
        self.population_columns = pd.DataFrame()
        self._presereved_population_columns = None

    def setup(self):
        pass

    def reset(self):
        pass

    def register(self, simulation):
        pass

    def deregister(self, simulation):
        pass

    def load_population_columns(self, path_prefix, population_size):
        pass

    def load_data(self, path_prefix):
        pass

    def years_lived_with_disability(self, population):
        return 0.0

    def mortality_rates(self, population, rates):
        return rates

    def incidence_rates(self, population, rates, label):
        return rates

class BaseSimulationModule(SimulationModule):
    def __init__(self):
        super(BaseSimulationModule, self).__init__()
        self.register_event_listener(self.advance_age, 'time_step', priority=0)
        self.register_event_listener(self.mortality_handler, 'time_step', priority=1)

    def load_population_columns(self, path_prefix, population_size):
        self.population_columns = self.population_columns.join(pd.read_csv(os.path.join(path_prefix, 'age.csv')), how='outer')
        self.population_columns = self.population_columns.assign(fractional_age=self.population_columns.age.astype(float))
        self.population_columns = self.population_columns.join(pd.read_csv(os.path.join(path_prefix, 'sex.csv')))
        self.population_columns = self.population_columns.join(pd.DataFrame({'alive': [True]*len(self.population_columns.age)}))

    def load_data(self, path_prefix):
        self.all_cause_mortality_rates = pd.read_csv('/home/j/Project/Cost_Effectiveness/dev/data_processed/Mortality_Rates.csv')
        self.all_cause_mortality_rates.columns = [col.lower() for col in self.all_cause_mortality_rates]
        self.life_table = pd.read_csv('/home/j/Project/Cost_Effectiveness/dev/data/gbd/interpolated_reference_life_table.csv')

    def advance_age(self, label, mask, simulation):
        simulation.population.loc[mask, 'fractional_age'] += simulation.last_time_step.days/365.0
        simulation.population.age = simulation.population.fractional_age.astype(int)

    def mortality_rates(self, population, rates):
        rates.mortality_rate += population.merge(self.all_cause_mortality_rates, on=['age', 'sex', 'year']).mortality_rate
        return rates

    @only_living
    def mortality_handler(self, label, mask, simulation):
        mortality_rate = simulation.mortality_rates(simulation.population)
        mask &= mask_for_rate(simulation.population, mortality_rate.mortality_rate)
        simulation.yll_by_year[simulation.current_time.year] += simulation.population.merge(self.life_table, on=['age'])[mask].ex.sum()
        simulation.population.loc[mask, 'alive'] = False
        simulation.emit_event('deaths', mask)
