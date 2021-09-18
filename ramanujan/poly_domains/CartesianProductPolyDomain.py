import os
import json
from .AbstractPolyDomains import AbstractPolyDomains
from ..utils.utils import iter_series_items_from_compact_poly
from itertools import product
from copy import deepcopy
from numpy import array_split
from hashlib import md5

CHECKPOINT_DUMP_SIZE = 5_000


class CartesianProductPolyDomain(AbstractPolyDomains):
    """
    This poly domain will generate all combinations for a(n) and b(n) coefs without complex dependence between the two
    """
    def __init__(self, a_deg, a_coef_range, b_deg, b_coef_range, an_leading_coef_positive=True, name_prefix_for_cache='', 
        *args, **kwargs):
        """
        If all of an's coefs can get both positive and negative values, then we might get two iterations for any set of
        coefs, with opposite signs. Those two series will converge to the same value, but with a different sign, hence
        it is a redundant run we can skip. Based on an_leading_coef_positive we will try to detect those cases and skip
        them
        """
        self.a_deg = a_deg
        # expanding the range to a different range for each coef
        # allows us to use the same functions for decedent classes
        self.a_coef_range = [list(a_coef_range) for _ in range(a_deg + 1)]
        if an_leading_coef_positive and self.a_coef_range[-1][0] <= 0:
            self.a_coef_range[0][0] = 1

        self.b_deg = b_deg
        self.b_coef_range = [b_coef_range for _ in range(b_deg + 1)]
        self.name_prefix_for_cache = name_prefix_for_cache

        self._setup_metadata()
        super().__init__()

    def _setup_metadata(self):
        """
        This function generates and stores values that should not change throughout the run.
        It continues __init__'s job, but holds code that is used in classes that extend this class, so it was
        moved to a separate function.
        """
        # Before creating values for series sizes, or iteration ranges, check if we have a checkpoint file from previous 
        # execution that stopped without finishing 
        identifyer = bytes(str(self.a_coef_range) + ';' + str(self.b_coef_range), 'ascii')
        domain_ranges_hash = md5(identifyer).hexdigest()
        self.checkpoint_file_name = self.name_prefix_for_cache + domain_ranges_hash + '.json'

        self.checkpoint = {}
        # As default, the last checkpoint is the first iteration - so no data was calculated yet
        self.checkpoint['a'] = [coef_range[0] for coef_range in self.a_coef_range]
        self.checkpoint['b'] = [coef_range[0] for coef_range in self.b_coef_range]
        if os.path.isfile(self.checkpoint_file_name):
            # If a checkpoint file is present, we'll try to load the data from it
            try:
                with open(self.checkpoint_file_name, 'r') as f:
                    self.checkpoint = json.load(f)
                    print('loaded!')
                    print(self.checkpoint)
            except Exception as e:
                print(f'checkpoint file {self.checkpoint_file_name} loading failed:')
                print(e)
                print(f'Moving it to {self.checkpoint_file_name}.corrupted')
                os.rename(self.checkpoint_file_name, self.checkpoint_file_name + '.corrupted')
        self.checkpoint['a'] = tuple(self.checkpoint['a'])
        self.checkpoint['b'] = tuple(self.checkpoint['b'])

        self.an_length = self.get_an_length()
        self.bn_length = self.get_bn_length()
        self.num_iterations = self.an_length * self.bn_length

        self.an_domain_range, self.bn_domain_range = self.dump_domain_ranges()
        

    @staticmethod
    def _range_size(coef_range):
        return coef_range[1] - coef_range[0] + 1

    @staticmethod
    def domain_size_by_var_ranges(var_ranges):
        size = 1
        for var_range in var_ranges:
            size *= CartesianProductPolyDomain._range_size(var_range)
        return size

    @staticmethod
    def expand_coef_range_to_full_domain(coef_ranges):
        return [[i for i in range(coef[0], coef[1] + 1)] for coef in coef_ranges]

    def get_an_length(self):
        return CartesianProductPolyDomain.domain_size_by_var_ranges(self.a_coef_range)

    def get_bn_length(self):
        return CartesianProductPolyDomain.domain_size_by_var_ranges(self.b_coef_range)

    @staticmethod
    def get_poly_an_lead_coef(an_coefs):
        return an_coefs[0]

    @staticmethod
    def get_poly_bn_lead_coef(bn_coefs):
        return bn_coefs[0]

    @staticmethod
    def _get_compact_poly_deg(coeffs):
        deg = len(coeffs) - 1
        for coef in coeffs:
            if coef != 0:
                return deg
            else:
                deg -= 1

    @staticmethod
    def get_bn_degree(bn_coefs):
        self._get_compact_poly_deg(bn_coefs)

    @staticmethod
    def get_bn_degree(bn_coefs):
        self._get_compact_poly_deg(an_coefs)

    @staticmethod
    def get_calculation_method():
        # both an and bn are regular compact polys
        return iter_series_items_from_compact_poly, \
            iter_series_items_from_compact_poly

    def dump_domain_ranges(self):
        an_domain = CartesianProductPolyDomain.expand_coef_range_to_full_domain(self.a_coef_range)
        bn_domain = CartesianProductPolyDomain.expand_coef_range_to_full_domain(self.b_coef_range)

        return an_domain, bn_domain

    def update_checkpoint(self, current_a_coef, current_b_coef):
        print('dumping')
        print(current_a_coef, current_b_coef)
        with open(self.checkpoint_file_name, 'w') as f:
            json.dump({'a': current_a_coef, 'b':current_b_coef}, f)

    def delete_checkpoint(self):
        print(f'deleteing {self.checkpoint_file_name}')
        try:
            os.remove(self.checkpoint_file_name)
        except FileNotFoundError as e:
            print('Failed deleting cache file (might acurre on small domains that don\'t require it)')
            print(e)

    @staticmethod
    def _goto_checkpoint(iterator, location):
        # This way we don't cause a StopIteration exception by closing the generator at the end of the loop
        # Notice - this causes the required location to already by yielded, so you might want to handle this item
        # separately 
        while next(iterator) != tuple(location):
            pass

    def iter_polys(self, primary_looped_domain):
        '''
        This function iterate pairs of an and bn coefs from the domain. 
        Some enumerators cache series items, and primary_looped_domain is used to determine the 
        nested loop order that fit the caching mechanism 
        If a checkpoint file was successfully loaded, we'll start the iteration from this point, using 
        the following logic:
        We're storing the last itered an and the last itered bn
        For the outer loop, we can just start the iteration from the last saved location.
        For the first outer series iteration, some inner series items had already been calculated, so we can
        discard those items. From the next iteration onwards, we'll have to calculate all items in the inner loop

        to make variable names easier, we refer to the outer series as `pn` and the inner (secondary) series as `sn`
        '''
        if primary_looped_domain == 'a':
            pn_coef_range = self.a_coef_range
            pn_series_checkpoint = self.checkpoint['a']
            sn_coef_range = self.b_coef_range
            sn_series_checkpoint = self.checkpoint['b']
        else:
            pn_coef_range = self.b_coef_range
            pn_series_checkpoint = self.checkpoint['b']
            sn_coef_range = self.a_coef_range
            sn_series_checkpoint = self.checkpoint['a']

        pn_domain = CartesianProductPolyDomain.expand_coef_range_to_full_domain(pn_coef_range)
        sn_domain = CartesianProductPolyDomain.expand_coef_range_to_full_domain(sn_coef_range)

        # only use relevant data for the outer series
        pn_iterator = product(*pn_domain)
        CartesianProductPolyDomain._goto_checkpoint(pn_iterator, pn_series_checkpoint)

        # handle the first series with incomplete iterations separately
        pn_coef = pn_series_checkpoint
        sn_iterator = product(*sn_domain)
        CartesianProductPolyDomain._goto_checkpoint(sn_iterator, sn_series_checkpoint)

        yield self.checkpoint['a'], self.checkpoint['b']
        items_passed = 1

        for sn_coef in sn_iterator:
            if items_passed % CHECKPOINT_DUMP_SIZE == 0:
                if primary_looped_domain == 'a':
                    self.update_checkpoint(pn_coef, sn_coef)
                else:
                    self.update_checkpoint(sn_coef, pn_coef)
            if primary_looped_domain == 'a':
                yield pn_coef, sn_coef
            else:
                yield sn_coef, pn_coef
            items_passed += 1

        for pn_coef in pn_iterator:
            sn_iterator = product(*sn_domain)           
            for sn_coef in sn_iterator:
                if items_passed % CHECKPOINT_DUMP_SIZE == 0:
                    if primary_looped_domain == 'a':
                        self.update_checkpoint(pn_coef, sn_coef)
                    else:
                        self.update_checkpoint(sn_coef, pn_coef)
                if primary_looped_domain == 'a':
                    yield pn_coef, sn_coef
                else:
                    yield sn_coef, pn_coef
                items_passed += 1

        self.delete_checkpoint()

    def get_a_coef_iterator(self):
        return product(*self.an_domain_range)

    def get_b_coef_iterator(self):
        return product(*self.bn_domain_range)

    def get_individual_polys_generators(self):
        # for backwards compatibility.
        return self.get_a_coef_iterator(), self.get_b_coef_iterator()

    @staticmethod
    def _get_metadata_on_var_ranges(ranges, series):
        ranges_metadata = []
        for i, v in enumerate(ranges):
            ranges_metadata.append({
                'range': v,
                'size': v[1]-v[0]+1,
                'series': series,
                'index': i
                })
        return ranges_metadata

    def split_domains_to_processes(self, number_of_instances):
        """
        When using multiprocessing, we'll split the search domain to several polyDomain and iter over each one
        in a different process.
        This function will split the domain to number_of_instances sub-domains. To do so, we'll find the coef
        with the biggest range, and split it as evenly as possible to different instances.
        """
        all_coef_ranges = self._get_metadata_on_var_ranges(self.a_coef_range, 'a')
        all_coef_ranges += self._get_metadata_on_var_ranges(self.b_coef_range, 'b')

        biggest_range = max(all_coef_ranges, key=lambda x: x['size'])

        # when splitting over a huge number of processes (probably over different clients) we'll not be able to
        # split the domain using only one coef. If that's the case, we'll just split the biggest coef as much as 
        # we can, and use the same logic recursively over every sub-domain.
        number_of_sub_arrays = min(number_of_instances, biggest_range['size'])
        
        sub_domains = []
        for chunk_items in array_split(range(biggest_range['range'][0], biggest_range['range'][1] + 1),
                                       number_of_sub_arrays):
            chunk_range = [int(chunk_items[0]), int(chunk_items[-1])]
            next_instance = deepcopy(self)
            if biggest_range['series'] == 'a':
                next_instance.a_coef_range[biggest_range['index']] = chunk_range
            else:
                next_instance.b_coef_range[biggest_range['index']] = chunk_range

            next_instance._setup_metadata()
            sub_domains.append(next_instance)

        if biggest_range['size'] < number_of_instances:
            # divide the required instances over all of the sub domains
            smaller_sub_domains = []
            for i, sub_domain in zip(array_split(range(number_of_instances), len(sub_domains)), sub_domains):
                smaller_sub_domains += sub_domain.split_domains_to_processes(len(i))

            return smaller_sub_domains

        return sub_domains
